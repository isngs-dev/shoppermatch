import { Navigate, useParams } from "react-router-dom";
import { CampaignDetail } from "./CampaignDetail";
import { CampaignsPortal, type PortalTab } from "./CampaignsPortal";

const TAB_KEYS = new Set<string>(["active", "upcoming", "completed"]);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Single dynamic route ("/client/campaigns/:param") serves both the three
// tabbed portals ("/client/campaigns/active|upcoming|completed") and a
// campaign detail page ("/client/campaigns/{uuid}").
export function Campaigns() {
  const { param } = useParams();
  if (!param || (!TAB_KEYS.has(param) && !UUID_RE.test(param))) {
    return <Navigate to="/client/campaigns/active" replace />;
  }
  if (TAB_KEYS.has(param)) {
    return <CampaignsPortal tab={param as PortalTab} />;
  }
  return <CampaignDetail id={param} />;
}
