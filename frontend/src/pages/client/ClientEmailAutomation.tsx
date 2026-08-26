// Deliberately its own top-level page, separate from Outreach (Send
// Invitation/Templates). Outreach only makes sense scoped to one campaign
// (reached via that campaign's own Outreach tab); Email Automation runs
// across whichever campaign+shop you pick from its own selector, so it
// isn't campaign-scoped the same way and gets its own top-level nav entry.
import { BulkSendStatusCard } from "../Outreach";
import { EmailAutomationPanel } from "../EmailAutomation";

export function ClientEmailAutomation() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Email Automation</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Configure and run multi-step outreach sequences for AI-recommended shoppers, across any campaign.
        </p>
      </div>
      <BulkSendStatusCard />
      <EmailAutomationPanel compact />
    </div>
  );
}
