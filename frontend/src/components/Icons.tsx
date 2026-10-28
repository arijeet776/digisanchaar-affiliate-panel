import type { SVGProps } from "react";

const base = { width: 17, height: 17, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function Icon(props: Omit<SVGProps<SVGSVGElement>, "d"> & { d: string | string[] }) {
  const { d, ...rest } = props;
  const paths = Array.isArray(d) ? d : [d];
  return (
    <svg {...base} {...rest}>
      {paths.map((p, i) => (
        <path key={i} d={p} />
      ))}
    </svg>
  );
}

export const IconDashboard = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" />;
export const IconUsers = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M23 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"]} />;
export const IconManager = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"]} />;
export const IconCampaign = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1z", "M16 8a5 5 0 0 1 0 8", "M19 5a9 9 0 0 1 0 14"]} />;
export const IconLink = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.5 1.5", "M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.5-1.5"]} />;
export const IconReports = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M3 3v18h18", "M7 15l3-4 3 3 5-7"]} />;
export const IconFinancial = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 2v20", "M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"]} />;
export const IconIntegrations = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M16 3h5v5", "M8 21H3v-5", "M21 3l-7.5 7.5", "M3 21l7.5-7.5"]} />;
export const IconNotifications = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9", "M13.73 21a2 2 0 0 1-3.46 0"]} />;
export const IconSettings = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.11.35.31.66.58.9.27.24.6.4.95.46H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"]} />;
export const IconAudit = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M9 12l2 2 4-4", "M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9c2 0 3.85.66 5.33 1.77"]} />;
export const IconSupport = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 18v-6", "M12 8h.01", "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z"]} />;
export const IconProfile = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"]} />;
export const IconLogout = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"]} />;
export const IconMenu = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M3 6h18", "M3 12h18", "M3 18h18"]} />;
export const IconSun = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z", "M12 1v2", "M12 21v2", "M4.22 4.22l1.42 1.42", "M18.36 18.36l1.42 1.42", "M1 12h2", "M21 12h2", "M4.22 19.78l1.42-1.42", "M18.36 5.64l1.42-1.42"]} />;
export const IconMoon = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />;
export const IconClose = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M18 6L6 18", "M6 6l12 12"]} />;
export const IconSearch = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.35-4.35"]} />;
export const IconPlus = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 5v14", "M5 12h14"]} />;
export const IconChevronLeft = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M15 18l-6-6 6-6" />;
export const IconChevronRight = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M9 18l6-6-6-6" />;
export const IconShield = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />;

export const IconMail = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M4 6h16v12H4z", "M4 7l8 6 8-6"]} />;
export const IconLock = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 8 0v3"]} />;
export const IconEye = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"]} />;
export const IconEyeOff = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M3 3l18 18", "M10.6 6.1A10 10 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3.2 3.9", "M6.6 6.7C3.9 8.4 2 12 2 12s3.5 6 10 6c1.4 0 2.7-.3 3.8-.7"]} />;
export const IconCopy = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M9 9h11v11H9z", "M5 15V4h11"]} />;
export const IconClock = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v5l3 2"]} />;
export const IconGlobe = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M3 12h18", "M12 3c3 3 3 15 0 18", "M12 3c-3 3-3 15 0 18"]} />;
export const IconPhone = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />;
export const IconBuilding = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M4 21V4h11v17", "M15 9h5v12", "M8 8h3M8 12h3M8 16h3"]} />;
export const IconCalendar = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M4 6h16v14H4z", "M4 10h16", "M8 3v4M16 3v4"]} />;
export const IconCheck = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M5 12l5 5 9-10" />;
export const IconFilter = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M3 5h18l-7 8v6l-4-2v-4z" />;
export const IconTarget = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"]} />;
export const IconLayers = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d={["M12 3l9 5-9 5-9-5z", "M3 13l9 5 9-5"]} />;
export const IconBack = (p: SVGProps<SVGSVGElement>) => <Icon {...p} d="M15 18l-6-6 6-6" />;
