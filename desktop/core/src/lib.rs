//! Platform-independent logic of the HMS desktop shell.
//!
//! The desktop application is a thin shell: it remembers the address of the
//! hotel server and shows the web interface served by it. There is no local
//! database (every device works on the hotel server). This crate holds the
//! decisions that must be right on every platform and can be tested without
//! a webview: which server addresses are accepted, where the window may
//! navigate, how a connection failure is explained, where downloads go.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use url::Url;

// --- server address ------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UrlProblem {
    Empty,
    Invalid,
    /// Plain HTTP is only accepted for this computer (development).
    InsecureScheme,
    /// user:password@ in the address.
    Credentials,
}

fn is_loopback(host: &str) -> bool {
    matches!(host, "localhost" | "127.0.0.1" | "[::1]" | "::1")
}

/// Turn what the user typed into the server origin (`https://host[:port]/`).
///
/// * A missing scheme means HTTPS (`hms.hotel.local` → `https://hms.hotel.local/`).
/// * HTTPS is required, except for this computer (`http://localhost:5173`).
/// * Path, query and fragment are dropped: the interface is served at the root.
pub fn normalize_server_url(input: &str) -> Result<Url, UrlProblem> {
    let text = input.trim();
    if text.is_empty() {
        return Err(UrlProblem::Empty);
    }
    let with_scheme = if text.contains("://") {
        text.to_string()
    } else {
        format!("https://{text}")
    };
    let mut url = Url::parse(&with_scheme).map_err(|_| UrlProblem::Invalid)?;
    let host = url.host_str().ok_or(UrlProblem::Invalid)?.to_ascii_lowercase();
    if !url.username().is_empty() || url.password().is_some() {
        return Err(UrlProblem::Credentials);
    }
    match url.scheme() {
        "https" => {}
        "http" if is_loopback(&host) => {}
        "http" => return Err(UrlProblem::InsecureScheme),
        _ => return Err(UrlProblem::Invalid),
    }
    url.set_path("/");
    url.set_query(None);
    url.set_fragment(None);
    Ok(url)
}

pub fn same_origin(a: &Url, b: &Url) -> bool {
    a.scheme() == b.scheme()
        && a.host_str() == b.host_str()
        && a.port_or_known_default() == b.port_or_known_default()
}

/// The shell's own bundled pages (connection screen).
pub fn is_app_url(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => url.host_str() == Some("tauri.localhost"),
        _ => false,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Navigation {
    /// Stay in the window.
    Allow,
    /// A link to another site: open it in the system browser instead.
    OpenExternally,
    /// Never (javascript:, file:, data:...).
    Deny,
}

/// Where the main window may go: the hotel server and the shell's own pages.
pub fn navigation(url: &Url, server: Option<&Url>) -> Navigation {
    if is_app_url(url) || url.as_str() == "about:blank" {
        return Navigation::Allow;
    }
    if let Some(server) = server {
        if same_origin(url, server) {
            return Navigation::Allow;
        }
    }
    match url.scheme() {
        "http" | "https" | "mailto" | "tel" => Navigation::OpenExternally,
        _ => Navigation::Deny,
    }
}

// --- connection check -------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckKind {
    Ok,
    InvalidUrl,
    InsecureScheme,
    Unreachable,
    Timeout,
    /// The certificate is not trusted by this computer (e.g. the hotel's own CA
    /// was not installed).
    TlsUntrusted,
    Tls,
    /// Something answered, but it is not an HMS server.
    NotHms,
    HttpStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckResult {
    pub kind: CheckKind,
    pub url: Option<String>,
    pub status: Option<u16>,
    pub detail: Option<String>,
}

impl CheckResult {
    pub fn ok(&self) -> bool {
        self.kind == CheckKind::Ok
    }
}

impl From<UrlProblem> for CheckKind {
    fn from(p: UrlProblem) -> Self {
        match p {
            UrlProblem::InsecureScheme => CheckKind::InsecureScheme,
            _ => CheckKind::InvalidUrl,
        }
    }
}

/// Explain a transport error from its message chain (HTTP client errors are
/// nested; the TLS cause is only visible in the text).
pub fn classify_error(chain: &str) -> CheckKind {
    let text = chain.to_ascii_lowercase();
    let tls = [
        "certificate",
        "unknownissuer",
        "unknown issuer",
        "self signed",
        "self-signed",
        "invalidcertificate",
    ];
    if tls.iter().any(|k| text.contains(k)) {
        CheckKind::TlsUntrusted
    } else if text.contains("tls") || text.contains("handshake") || text.contains("ssl") {
        CheckKind::Tls
    } else if text.contains("timed out") || text.contains("timeout") {
        CheckKind::Timeout
    } else {
        CheckKind::Unreachable
    }
}

/// The server's `/api/v1/health` answer identifies an HMS server.
pub fn is_hms_health(body: &str) -> bool {
    #[derive(Deserialize)]
    struct Health {
        status: Option<String>,
        service: Option<String>,
    }
    serde_json::from_str::<Health>(body)
        .map(|h| h.status.as_deref() == Some("ok") && h.service.as_deref() == Some("hms"))
        .unwrap_or(false)
}

pub fn health_url(server: &Url) -> Url {
    server.join("api/v1/health").expect("static path")
}

// --- settings -------------------------------------------------------------------------

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Settings {
    pub server_url: Option<String>,
}

pub fn load_settings(path: &Path) -> Settings {
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

/// Written to a temporary file then renamed, so a crash never leaves a
/// half-written settings file.
pub fn save_settings(path: &Path, settings: &Settings) -> io::Result<()> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, serde_json::to_vec_pretty(settings)?)?;
    fs::rename(tmp, path)
}

// --- downloads ---------------------------------------------------------------------------

/// A safe file name: no directory parts, no control or reserved characters.
pub fn safe_file_name(suggested: &str) -> String {
    let base = suggested.rsplit(['/', '\\']).next().unwrap_or("");
    let cleaned: String = base
        .chars()
        .map(|c| {
            if c.is_control() || "<>:\"|?*".contains(c) {
                '_'
            } else {
                c
            }
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').to_string();
    if trimmed.is_empty() {
        "download".to_string()
    } else {
        trimmed
    }
}

/// Where to save a download in `dir` without overwriting an existing file:
/// `invoice.pdf`, then `invoice (1).pdf`, `invoice (2).pdf`...
pub fn download_target(dir: &Path, suggested: &str) -> PathBuf {
    let name = safe_file_name(suggested);
    let candidate = dir.join(&name);
    if !candidate.exists() {
        return candidate;
    }
    let (stem, ext) = match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i..]),
        _ => (name.as_str(), ""),
    };
    (1..)
        .map(|n| dir.join(format!("{stem} ({n}){ext}")))
        .find(|p| !p.exists())
        .expect("unbounded")
}

/// Documents the shell opens with the system viewer once downloaded.
pub fn open_after_download(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e.eq_ignore_ascii_case("pdf"))
}

// --- menu labels ---------------------------------------------------------------------------

pub struct MenuLabels {
    pub server: &'static str,
    pub change_server: &'static str,
    pub reload: &'static str,
    pub quit: &'static str,
}

/// Native menu labels in the five interface languages (system language).
pub fn menu_labels(locale: &str) -> MenuLabels {
    let lang = locale.to_ascii_lowercase();
    if lang.starts_with("fr") {
        MenuLabels {
            server: "Serveur",
            change_server: "Changer de serveur…",
            reload: "Recharger",
            quit: "Quitter",
        }
    } else if lang.starts_with("zh") {
        MenuLabels {
            server: "服务器",
            change_server: "更换服务器…",
            reload: "重新加载",
            quit: "退出",
        }
    } else if lang.starts_with("ru") {
        MenuLabels {
            server: "Сервер",
            change_server: "Сменить сервер…",
            reload: "Обновить",
            quit: "Выход",
        }
    } else if lang.starts_with("km") {
        MenuLabels {
            server: "ម៉ាស៊ីនមេ",
            change_server: "ប្ដូរម៉ាស៊ីនមេ…",
            reload: "ផ្ទុកឡើងវិញ",
            quit: "ចាកចេញ",
        }
    } else {
        MenuLabels {
            server: "Server",
            change_server: "Change server…",
            reload: "Reload",
            quit: "Quit",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn server_addresses_are_normalised_to_an_https_origin() {
        assert_eq!(
            normalize_server_url("hms.hotel.local").unwrap().as_str(),
            "https://hms.hotel.local/"
        );
        assert_eq!(
            normalize_server_url("  https://HMS.hotel.local:8443/front-desk?x=1#y ")
                .unwrap()
                .as_str(),
            "https://hms.hotel.local:8443/"
        );
        assert_eq!(
            normalize_server_url("192.168.1.20").unwrap().as_str(),
            "https://192.168.1.20/"
        );
        assert_eq!(
            normalize_server_url("http://localhost:5173").unwrap().as_str(),
            "http://localhost:5173/"
        );
        assert_eq!(
            normalize_server_url("http://127.0.0.1:8000/").unwrap().as_str(),
            "http://127.0.0.1:8000/"
        );
    }

    #[test]
    fn unsafe_or_invalid_addresses_are_refused() {
        assert_eq!(normalize_server_url("   "), Err(UrlProblem::Empty));
        assert_eq!(
            normalize_server_url("http://192.168.1.20"),
            Err(UrlProblem::InsecureScheme)
        );
        assert_eq!(
            normalize_server_url("https://admin:pw@hms.local"),
            Err(UrlProblem::Credentials)
        );
        assert_eq!(normalize_server_url("ftp://hms.local"), Err(UrlProblem::Invalid));
        assert_eq!(
            normalize_server_url("file:///etc/passwd"),
            Err(UrlProblem::Invalid)
        );
        assert_eq!(normalize_server_url("https://"), Err(UrlProblem::Invalid));
    }

    #[test]
    fn the_window_stays_on_the_hotel_server() {
        let server = u("https://hms.hotel.local/");
        let s = Some(&server);
        assert_eq!(
            navigation(&u("https://hms.hotel.local/reservations/1"), s),
            Navigation::Allow
        );
        assert_eq!(
            navigation(&u("https://hms.hotel.local:443/x"), s),
            Navigation::Allow
        );
        assert_eq!(
            navigation(&u("tauri://localhost/index.html"), s),
            Navigation::Allow
        );
        assert_eq!(
            navigation(&u("http://tauri.localhost/index.html?change=1"), s),
            Navigation::Allow
        );
        // Another port, scheme or host is another site.
        assert_eq!(
            navigation(&u("https://hms.hotel.local:8443/"), s),
            Navigation::OpenExternally
        );
        assert_eq!(
            navigation(&u("http://hms.hotel.local/"), s),
            Navigation::OpenExternally
        );
        assert_eq!(
            navigation(&u("https://www.booking.com/"), s),
            Navigation::OpenExternally
        );
        assert_eq!(
            navigation(&u("mailto:guest@example.com"), s),
            Navigation::OpenExternally
        );
        assert_eq!(navigation(&u("file:///etc/passwd"), s), Navigation::Deny);
        assert_eq!(navigation(&u("javascript:alert(1)"), s), Navigation::Deny);
        // Before a server is chosen, only the shell's pages.
        assert_eq!(
            navigation(&u("https://hms.hotel.local/"), None),
            Navigation::OpenExternally
        );
    }

    #[test]
    fn connection_errors_are_explained() {
        let untrusted =
            "error sending request: client error (Connect): invalid peer certificate: UnknownIssuer";
        assert_eq!(classify_error(untrusted), CheckKind::TlsUntrusted);
        assert_eq!(
            classify_error("received fatal alert: HandshakeFailure (tls)"),
            CheckKind::Tls
        );
        assert_eq!(classify_error("operation timed out"), CheckKind::Timeout);
        assert_eq!(
            classify_error("tcp connect error: Connection refused (os error 111)"),
            CheckKind::Unreachable
        );
        assert_eq!(
            classify_error("dns error: failed to lookup address information"),
            CheckKind::Unreachable
        );
    }

    #[test]
    fn only_an_hms_server_is_accepted() {
        assert!(is_hms_health(
            r#"{"status":"ok","service":"hms","version":"0.1.0","realtime":true}"#
        ));
        assert!(!is_hms_health(r#"{"status":"ok"}"#)); // some other application
        assert!(!is_hms_health(r#"{"status":"degraded","service":"hms"}"#));
        assert!(!is_hms_health("<html>router login</html>"));
        assert_eq!(
            health_url(&u("https://hms.local/")).as_str(),
            "https://hms.local/api/v1/health"
        );
    }

    #[test]
    fn settings_round_trip_and_tolerate_damage() {
        let dir = std::env::temp_dir().join(format!("hms-desktop-test-{}", std::process::id()));
        let path = dir.join("settings.json");
        assert_eq!(load_settings(&path), Settings::default());
        let s = Settings {
            server_url: Some("https://hms.local/".into()),
        };
        save_settings(&path, &s).unwrap();
        assert_eq!(load_settings(&path), s);
        fs::write(&path, "{ not json").unwrap();
        assert_eq!(load_settings(&path), Settings::default()); // damaged file: ask again
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn downloads_never_overwrite_or_escape_the_folder() {
        assert_eq!(safe_file_name("../../etc/passwd"), "passwd");
        assert_eq!(safe_file_name("C:\\Windows\\evil.pdf"), "evil.pdf");
        assert_eq!(safe_file_name("in<v>oice?.pdf"), "in_v_oice_.pdf");
        assert_eq!(safe_file_name("..."), "download");
        let dir = std::env::temp_dir().join(format!("hms-dl-test-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        assert_eq!(download_target(&dir, "invoice.pdf"), dir.join("invoice.pdf"));
        fs::write(dir.join("invoice.pdf"), b"x").unwrap();
        fs::write(dir.join("invoice (1).pdf"), b"x").unwrap();
        assert_eq!(download_target(&dir, "invoice.pdf"), dir.join("invoice (2).pdf"));
        assert!(
            open_after_download(Path::new("/tmp/a.PDF")) && !open_after_download(Path::new("/tmp/a.csv"))
        );
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn menu_follows_the_system_language() {
        assert_eq!(menu_labels("fr-FR").change_server, "Changer de serveur…");
        assert_eq!(menu_labels("km_KH").quit, "ចាកចេញ");
        assert_eq!(menu_labels("de-DE").reload, "Reload");
    }
}
