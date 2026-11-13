// Strings of the connection screen (the rest of the interface comes from the
// hotel server, with its own translations). {name} placeholders are replaced.
export const LANGUAGES = { en: 'English', fr: 'Français', 'zh-CN': '简体中文', ru: 'Русский', km: 'ខ្មែរ' };

export const STRINGS = {
  en: {
    title: 'Connect to the hotel server',
    intro: 'Enter the address of your hotel’s HMS server. Ask your administrator if you do not know it.',
    label: 'Server address',
    placeholder: 'hms.myhotel.local',
    test: 'Test',
    connect: 'Connect',
    connecting: 'Connecting to {url}…',
    retrying: 'Next attempt in {s} s',
    retry_now: 'Retry now',
    change: 'Change server',
    ok: 'HMS server found at {url}.',
    details: 'Technical details',
    language: 'Language',
    footer: 'The interface is loaded from your hotel server. Nothing is stored on this computer except the server address.',
    results: {
      invalid_url: 'This address is not valid.',
      insecure_scheme: 'The connection must be secure (https://). Plain http:// is only accepted for this computer.',
      unreachable: 'The server cannot be reached. Check that it is switched on and that this computer is on the hotel network.',
      timeout: 'The server did not answer in time.',
      tls_untrusted:
        'This computer does not trust the server’s certificate. Install the hotel’s certificate on this computer (installation guide, section 3), then try again.',
      tls: 'The secure connection to the server failed.',
      not_hms: 'Something answered at this address, but it is not an HMS server.',
      http_status: 'The server answered with an error (HTTP {status}).',
    },
  },
  fr: {
    title: 'Connexion au serveur de l’hôtel',
    intro: 'Saisissez l’adresse du serveur HMS de votre hôtel. Demandez-la à votre administrateur si vous ne la connaissez pas.',
    label: 'Adresse du serveur',
    placeholder: 'hms.monhotel.local',
    test: 'Tester',
    connect: 'Se connecter',
    connecting: 'Connexion à {url}…',
    retrying: 'Nouvel essai dans {s} s',
    retry_now: 'Réessayer maintenant',
    change: 'Changer de serveur',
    ok: 'Serveur HMS trouvé à l’adresse {url}.',
    details: 'Détails techniques',
    language: 'Langue',
    footer: 'L’interface est chargée depuis le serveur de votre hôtel. Rien n’est enregistré sur cet ordinateur, sauf l’adresse du serveur.',
    results: {
      invalid_url: 'Cette adresse n’est pas valide.',
      insecure_scheme: 'La connexion doit être sécurisée (https://). Le simple http:// n’est accepté que pour cet ordinateur.',
      unreachable: 'Le serveur est injoignable. Vérifiez qu’il est allumé et que cet ordinateur est bien sur le réseau de l’hôtel.',
      timeout: 'Le serveur n’a pas répondu à temps.',
      tls_untrusted:
        'Cet ordinateur ne fait pas confiance au certificat du serveur. Installez le certificat de l’hôtel sur cet ordinateur (guide d’installation, section 3), puis réessayez.',
      tls: 'La connexion sécurisée au serveur a échoué.',
      not_hms: 'Quelque chose répond à cette adresse, mais ce n’est pas un serveur HMS.',
      http_status: 'Le serveur a répondu par une erreur (HTTP {status}).',
    },
  },
  'zh-CN': {
    title: '连接到酒店服务器',
    intro: '请输入酒店 HMS 服务器的地址。如不清楚，请联系管理员。',
    label: '服务器地址',
    placeholder: 'hms.myhotel.local',
    test: '测试',
    connect: '连接',
    connecting: '正在连接 {url}…',
    retrying: '{s} 秒后重试',
    retry_now: '立即重试',
    change: '更换服务器',
    ok: '已在 {url} 找到 HMS 服务器。',
    details: '技术详情',
    language: '语言',
    footer: '界面从酒店服务器加载。除服务器地址外，本计算机不保存任何数据。',
    results: {
      invalid_url: '该地址无效。',
      insecure_scheme: '必须使用安全连接（https://）。仅连接本机时才可使用 http://。',
      unreachable: '无法连接到服务器。请检查服务器是否已开启，以及本计算机是否已连接到酒店网络。',
      timeout: '服务器未及时响应。',
      tls_untrusted:
        '本计算机不信任该服务器的证书。请在本计算机上安装酒店的证书（见安装指南第 3 节），然后重试。',
      tls: '与服务器的安全连接失败。',
      not_hms: '该地址有响应，但不是 HMS 服务器。',
      http_status: '服务器返回错误（HTTP {status}）。',
    },
  },
  ru: {
    title: 'Подключение к серверу отеля',
    intro: 'Введите адрес сервера HMS вашего отеля. Если вы его не знаете, обратитесь к администратору.',
    label: 'Адрес сервера',
    placeholder: 'hms.myhotel.local',
    test: 'Проверить',
    connect: 'Подключиться',
    connecting: 'Подключение к {url}…',
    retrying: 'Повторная попытка через {s} с',
    retry_now: 'Повторить сейчас',
    change: 'Сменить сервер',
    ok: 'Сервер HMS найден по адресу {url}.',
    details: 'Технические подробности',
    language: 'Язык',
    footer: 'Интерфейс загружается с сервера вашего отеля. На этом компьютере хранится только адрес сервера.',
    results: {
      invalid_url: 'Некорректный адрес.',
      insecure_scheme: 'Подключение должно быть защищённым (https://). Обычный http:// допускается только для этого компьютера.',
      unreachable: 'Сервер недоступен. Убедитесь, что он включён и что этот компьютер подключён к сети отеля.',
      timeout: 'Сервер не ответил вовремя.',
      tls_untrusted:
        'Этот компьютер не доверяет сертификату сервера. Установите сертификат отеля на этот компьютер (руководство по установке, раздел 3) и повторите попытку.',
      tls: 'Не удалось установить защищённое подключение к серверу.',
      not_hms: 'По этому адресу получен ответ, но это не сервер HMS.',
      http_status: 'Сервер вернул ошибку (HTTP {status}).',
    },
  },
  km: {
    title: 'ភ្ជាប់ទៅម៉ាស៊ីនមេរបស់សណ្ឋាគារ',
    intro: 'សូមបញ្ចូលអាសយដ្ឋានម៉ាស៊ីនមេ HMS របស់សណ្ឋាគារអ្នក។ ប្រសិនបើអ្នកមិនដឹង សូមសួរអ្នកគ្រប់គ្រងប្រព័ន្ធ។',
    label: 'អាសយដ្ឋានម៉ាស៊ីនមេ',
    placeholder: 'hms.myhotel.local',
    test: 'សាកល្បង',
    connect: 'ភ្ជាប់',
    connecting: 'កំពុងភ្ជាប់ទៅ {url}…',
    retrying: 'នឹងព្យាយាមម្ដងទៀតក្នុងរយៈពេល {s} វិនាទី',
    retry_now: 'ព្យាយាមម្ដងទៀតឥឡូវនេះ',
    change: 'ប្ដូរម៉ាស៊ីនមេ',
    ok: 'បានរកឃើញម៉ាស៊ីនមេ HMS នៅ {url}។',
    details: 'ព័ត៌មានលម្អិតបច្ចេកទេស',
    language: 'ភាសា',
    footer: 'ចំណុចប្រទាក់ត្រូវបានផ្ទុកពីម៉ាស៊ីនមេរបស់សណ្ឋាគារអ្នក។ គ្មានអ្វីត្រូវបានរក្សាទុកនៅលើកុំព្យូទ័រនេះទេ លើកលែងតែអាសយដ្ឋានម៉ាស៊ីនមេ។',
    results: {
      invalid_url: 'អាសយដ្ឋាននេះមិនត្រឹមត្រូវទេ។',
      insecure_scheme: 'ការតភ្ជាប់ត្រូវតែមានសុវត្ថិភាព (https://)។ http:// ធម្មតា អាចប្រើបានតែសម្រាប់កុំព្យូទ័រនេះប៉ុណ្ណោះ។',
      unreachable: 'មិនអាចភ្ជាប់ទៅម៉ាស៊ីនមេបានទេ។ សូមពិនិត្យថា ម៉ាស៊ីនមេត្រូវបានបើក ហើយកុំព្យូទ័រនេះបានភ្ជាប់ទៅបណ្ដាញរបស់សណ្ឋាគារ។',
      timeout: 'ម៉ាស៊ីនមេមិនបានឆ្លើយតបទាន់ពេលទេ។',
      tls_untrusted:
        'កុំព្យូទ័រនេះមិនទុកចិត្តវិញ្ញាបនបត្ររបស់ម៉ាស៊ីនមេទេ។ សូមដំឡើងវិញ្ញាបនបត្ររបស់សណ្ឋាគារនៅលើកុំព្យូទ័រនេះ (សៀវភៅណែនាំការដំឡើង ផ្នែកទី 3) រួចព្យាយាមម្ដងទៀត។',
      tls: 'ការតភ្ជាប់ប្រកបដោយសុវត្ថិភាពទៅម៉ាស៊ីនមេបានបរាជ័យ។',
      not_hms: 'មានការឆ្លើយតបពីអាសយដ្ឋាននេះ ប៉ុន្តែវាមិនមែនជាម៉ាស៊ីនមេ HMS ទេ។',
      http_status: 'ម៉ាស៊ីនមេបានឆ្លើយតបដោយកំហុស (HTTP {status})។',
    },
  },
};

export function pickLanguage(saved, browser) {
  const wanted = saved || browser || 'en';
  if (wanted in LANGUAGES) return wanted;
  if (wanted.toLowerCase().startsWith('zh')) return 'zh-CN';
  const short = wanted.slice(0, 2).toLowerCase();
  return short in LANGUAGES ? short : 'en';
}

export function translate(lang, key, params = {}) {
  const pick = (table) => key.split('.').reduce((o, k) => (o == null ? o : o[k]), table);
  const text = pick(STRINGS[lang] ?? {}) ?? pick(STRINGS.en) ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k) => (k in params ? String(params[k]) : `{${k}}`));
}
