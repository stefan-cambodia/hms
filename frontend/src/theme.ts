import { createTheme, type MantineColorsTuple, rem } from '@mantine/core';

// Deep lagoon teal: calm, premium, high contrast on warm neutrals.
const lagoon: MantineColorsTuple = [
  '#e7f6f5',
  '#d4ebe9',
  '#a8d6d2',
  '#79c0ba',
  '#52aca5',
  '#3a9f97',
  '#2b8f88',
  '#1d7a74',
  '#106661',
  '#00524d',
];

// Warm brass accent used sparingly (arrivals, highlights).
const brass: MantineColorsTuple = [
  '#fdf6e7',
  '#f7eacd',
  '#efd49b',
  '#e6bd64',
  '#dfaa38',
  '#db9e1d',
  '#d9980d',
  '#c08300',
  '#ab7400',
  '#946300',
];

// Font stack: Inter covers Latin and Cyrillic; the Noto fonts take over
// glyph-by-glyph for Khmer and Chinese. All fonts are self-hosted, so the app
// renders correctly on a hotel LAN without Internet access.
export const FONT_STACK =
  "'Inter Variable', 'Noto Sans Khmer', 'Noto Sans SC', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export const theme = createTheme({
  primaryColor: 'lagoon',
  primaryShade: { light: 7, dark: 5 },
  colors: { lagoon, brass },
  fontFamily: FONT_STACK,
  headings: {
    fontFamily: FONT_STACK,
    fontWeight: '650',
    sizes: {
      h1: { fontSize: rem(28), lineHeight: '1.25' },
      h2: { fontSize: rem(22), lineHeight: '1.3' },
      h3: { fontSize: rem(18), lineHeight: '1.35' },
      h4: { fontSize: rem(16), lineHeight: '1.4' },
    },
  },
  defaultRadius: 'md',
  cursorType: 'pointer',
  respectReducedMotion: true,
  components: {
    Button: { defaultProps: { radius: 'md' } },
    // Sentence case: uppercase badges read poorly in Cyrillic and add noise.
    Badge: { styles: { root: { textTransform: 'none', fontWeight: 600 } } },
    Card: { defaultProps: { radius: 'lg', withBorder: true, padding: 'lg' } },
    Paper: { defaultProps: { radius: 'lg' } },
    Modal: { defaultProps: { radius: 'lg', centered: true, overlayProps: { blur: 2 } } },
    Drawer: { defaultProps: { position: 'right', size: 'lg' } },
    TextInput: { defaultProps: { radius: 'md' } },
    Table: { defaultProps: { verticalSpacing: 'sm', highlightOnHover: true } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 300 } },
  },
});
