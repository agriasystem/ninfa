import type { ReactNode, SVGProps } from "react";

/**
 * The small, purely PRESENTATIONAL icon set of the Home UI V1 shell (navigation, domain strip,
 * suggested questions, Mia bar). Every icon is `aria-hidden` - the control that contains it always
 * carries its own accessible name - and draws with `currentColor`, so state colour lives in CSS.
 *
 * These are icons and logos, not analytical graphics: the Home still shows ZERO charts (see
 * docs/architecture/home-ui-v1.md, "No graphs").
 */
type IconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function Icon({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export function HomeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 11.5 12 4l9 7.5V20H3z" />
      <path d="M9.5 20v-6h5v6" />
    </Icon>
  );
}

export function DecisionsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="4" y="3" width="16" height="18" rx="2.5" />
      <path d="M8 9h8M8 13h8M8 17h4" />
    </Icon>
  );
}

export function BarsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="12" width="4" height="8" rx="1" />
      <rect x="10" y="4" width="4" height="16" rx="1" />
      <rect x="16.5" y="9" width="4" height="11" rx="1" />
    </Icon>
  );
}

export function DatabaseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </Icon>
  );
}

export function UserIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21c0-4 3.4-6 7.5-6s7.5 2 7.5 6" />
    </Icon>
  );
}

export function UsersIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c0-3.6 2.9-5.5 6.5-5.5s6.5 1.9 6.5 5.5" />
      <path d="M16 4.7a3.5 3.5 0 0 1 0 6.6M18 14.8c2 .6 3.5 2.1 3.5 5.2" />
    </Icon>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8" strokeWidth="3" strokeDasharray="2.6 3.6" />
      <circle cx="12" cy="12" r="6.2" />
      <circle cx="12" cy="12" r="2.6" />
    </Icon>
  );
}

export function NetworkIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="5" r="2.3" />
      <circle cx="5" cy="19" r="2.3" />
      <circle cx="19" cy="19" r="2.3" />
      <path d="M12 7.3v4.2M12 11.5 6.2 17M12 11.5l5.8 5.5" />
    </Icon>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10.5" cy="10.5" r="7" />
      <path d="m16 16 5 5" />
    </Icon>
  );
}

export function ListIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 6h12M9 12h12M9 18h12" />
      <circle cx="4.5" cy="6" r="0.8" fill="currentColor" />
      <circle cx="4.5" cy="12" r="0.8" fill="currentColor" />
      <circle cx="4.5" cy="18" r="0.8" fill="currentColor" />
    </Icon>
  );
}

export function TrendIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m3 17 6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </Icon>
  );
}

export function TargetIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.9" />
    </Icon>
  );
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 12h15M13 6l6 6-6 6" />
    </Icon>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 19V5M6 11l6-6 6 6" />
    </Icon>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m6 9 6 6 6-6" />
    </Icon>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 11a8 8 0 0 0-14.3-4.5L4 8.5" />
      <path d="M4 4v4.5h4.5" />
      <path d="M4 13a8 8 0 0 0 14.3 4.5l1.7-2" />
      <path d="M20 20v-4.5h-4.5" />
    </Icon>
  );
}

/** A quiet open ring; the caller spins it (CSS) while a request is in flight. */
export function SpinnerIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </Icon>
  );
}

// --- Struttura UI V1 ------------------------------------------------------------------------------

/** The structure itself. Drawn with <rect> and <line> ONLY, on purpose: as a sidebar icon it must keep
 * its outline when active, and the active state fills every <path> and paints the last one white (that
 * is the Oggi house's look - see `.nav-item[aria-current]` in globals.css). */
export function BuildingIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="5" y="3" width="14" height="18" rx="1.8" />
      <line x1="9" y1="8" x2="10.2" y2="8" />
      <line x1="13.8" y1="8" x2="15" y2="8" />
      <line x1="9" y1="12" x2="10.2" y2="12" />
      <line x1="13.8" y1="12" x2="15" y2="12" />
      <rect x="10" y="16" width="4" height="5" rx="0.6" />
    </Icon>
  );
}

/** A house with a pencil: "Modifica struttura". */
export function EditStructureIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 11 12 4.5 19.5 11" />
      <path d="M6.5 9.5V19.5h4M17.5 9.5v1.5" />
      <path d="m12.8 19.3.5-2.5 4.9-4.9a1.5 1.5 0 0 1 2.1 2.1l-4.9 4.9z" />
    </Icon>
  );
}

export function BedIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 19.5V5M3.5 16h17v3.5M3.5 12.5H13a3.5 3.5 0 0 1 3.5 3.5" />
      <rect x="6" y="8.8" width="4.6" height="3.7" rx="1.2" />
    </Icon>
  );
}

export function CalendarIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="5" width="17" height="15.5" rx="3" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
      <rect x="8" y="13.2" width="3.2" height="3.2" rx="0.7" />
    </Icon>
  );
}

export function PencilIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m4 20 1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z" />
      <path d="m14.5 6.5 3 3" />
    </Icon>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

/** Three dots: the "more actions" trigger. */
export function MoreIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="5.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/** A solid star; the caller colours it and dims the ones that are not earned. */
export function StarIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path
        d="m12 3.2 2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 17l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8z"
        fill="currentColor"
        stroke="none"
      />
    </Icon>
  );
}

/** A filled disc with a check: a connected source. */
export function CheckCircleIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="10" fill="currentColor" stroke="none" />
      <path d="m7.6 12.4 3 3 5.8-6" stroke="#fff" strokeWidth="2.2" />
    </Icon>
  );
}

export function CloudIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7.2 18.5h10.1a3.8 3.8 0 0 0 .6-7.55 5.6 5.6 0 0 0-10.8-1.2A4.4 4.4 0 0 0 7.2 18.5z" />
    </Icon>
  );
}

export function DocumentIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
      <path d="M14 3v4h4M9 12.5h6M9 16.5h6" />
    </Icon>
  );
}

/** A window split into a header and a side panel: the property management system. */
export function LayoutIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="4" width="17" height="16" rx="2.5" />
      <path d="M3.5 9h17M9.5 9v11" />
    </Icon>
  );
}
