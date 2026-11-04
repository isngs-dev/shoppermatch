<!-- audiences: staff -->
# Client portal and admin: how to do things, page by page

## Navigation and shortcuts
The Client portal top bar has Dashboard, Campaigns, Email Automation, Social Media, Insights and Reports, plus a Quick jump search (press Ctrl+K), the notification bell, the light/dark theme toggle and your profile menu (Profile & settings, sign out). The chat assistant is the round button bottom-left and a microphone button bottom-right turns on the "Hey Assistant" voice assistant. The Admin portal has Dashboard, Tracking, Insights, Users, Client Activity, Audit Logs, Integrations and Settings.

## Dashboard (client)
The client Dashboard shows KPI tiles (active campaigns, active shoppers, open shops, declined responses), an outreach volume chart by stage, a conversion funnel (Sent, Delivered, Opened, Clicked, Accepted), and a campaign health donut (On Track, Attention Required, Completed). Use it for a quick overview, then open Campaigns to act.

## Campaigns list: active, upcoming and completed
Campaigns is split into three buckets. Active are live campaigns (including in progress and filled ones), Upcoming are drafts, scheduled and upcoming ones (recruitment and invitation preparation, not yet active assignments), and Completed are finished campaigns. Open a campaign to see its detail page with tabs: Overview, Map, Shops, Shoppers, AI Recommendations, Outreach, Tracking and Insights.

## Campaign Overview tab
Overview shows the campaign description, client, status, created date, deadline and Total shops with how many are completed and remaining, plus the outreach funnel and the number of declined responses. EXPORT PDF, EXPORT XLSX and EXPORT CSV buttons download a campaign report. The cards above the tabs show Total shops, Completed, Remaining, Progress and Invitations.

## Campaign Map tab
The Map shows every shop of the campaign on a live map that refreshes about every 10 seconds. A shop marker is green for healthy coverage, amber for medium and red for low coverage. Around each shop the top AI-matched shoppers are shown as purple dots (best three) and grey dots (other eligible shoppers). Hover a marker to see its details without clicking; click a shop marker for a popup with a View Shop button.

## Campaign Shops tab
Shops lists every shop with its location, required shoppers, how many are invited and its coverage (healthy, medium or low). Open a shop for its detail drawer, which includes the shop's recommended shoppers and a link to AI Recommendations for that shop.

## Campaign Shoppers tab
Shoppers lists the shoppers invited for this campaign with their response and status. Client users see aggregate counts and not personal contact details; admins can open full profiles.

## Choose shoppers with AI Recommendations
Open the campaign's AI Recommendations tab, choose a shop from the Shop dropdown (each shows "filled" or "needs N more"), and the AI analyses eligible shoppers automatically. If the AI found exactly the shoppers the shop needs you see "AI recommends N shoppers" with those shoppers ticked; press Approve N and Go to Outreach to create their invitations and jump to Outreach. If the shop is already staffed it shows "Fully staffed" with a Go to Outreach button. If there are not enough shoppers it shows a recruitment gap with steps to close it.

## Close a recruitment gap
When a shop is short, the AI Recommendations tab offers steps in order: 1) widen the search, with a button like Expand to 75 km that jumps straight to the radius that reaches enough shoppers; 2) add or raise a bonus, where the AI recommends an amount sized to the shop's pay and the gap, and a bonus pays for the trip so shoppers further away also qualify (each dollar of bonus extends reach by 10 km); 3) recruit shoppers near the shop through Social Media when nobody is within a visitable distance. Widening and adding a bonus both re-run the matching so shoppers appear in the list straight away.

## Back-up shoppers and over-selection
By default a shop cannot be invited beyond its required number. To invite backups, open More candidates (shown once the shop has all it needs) and turn on Allow over-selection for that shop. A decline frees the slot again. Over-selection is per shop and can be turned off again.

## Add or edit a shop bonus
A bonus is extra money for a shop that is hard to fill, on top of its compensation. Press Add bonus (or Edit bonus) on the AI Recommendations tab, enter an amount and optional note, and save. It is funded and paid by the client directly to the shopper who completes the shop; ShopperMatch does not process the payment, it tracks the pledge and sends a reminder when ISN marks the shop completed. The AI can suggest an amount (Add Suggested Bonus). A bonus already awarded cannot be changed or removed.

## Auto Assign Shoppers (whole campaign)
The AI Assignment Optimization card at the bottom of AI Recommendations finds the best shopper-to-shop assignment across the whole campaign at once, never proposing the same shopper for two shops and never more than a shop needs. Enter a search radius and press Auto Assign Shoppers. Shops it cannot fully staff are listed with Expand to N km, Add bonus and Review shop actions, and Widen all and re-run widens every short shop. Approve All turns the proposal into invitations and takes you to Outreach with everything approved listed and ticked.

## Outreach: send invitations
Outreach has a Compose panel: choose the Campaign, then Send to. All shops · all required shoppers selects every shop and every shopper each shop needs for one combined send (the lists are read-only). Choose individually lets you tick shops and shoppers yourself. Shoppers who were already approved in AI Recommendations show an Approved tag and sending uses that invitation without creating a duplicate. Pick a template, edit the subject and the live body preview (insert variables such as shopper name, shop, location, compensation, deadline and the assignment link), optionally Generate with AI to personalise the email, use Send Test, then send. A Back to AI Recommendations link is at the top.

## Send a test email or a follow-up
Select exactly one shopper to unlock Send Test, which sends the composed email to an address you choose without touching campaign metrics (clicks on a test email still register against the real invitation). A follow-up can be sent for an invitation that was already sent. Each invitation can be sent only once; the system blocks accidental double sends.

## Email Automation tabs
Email Automation has five tabs: Automations (multi-step email sequences), Bulk Voice Call, Email Tracking, Call Tracking and Templates. An automation emails every recommended shopper in a campaign (or one shop) in steps with waiting periods, and can start, pause and resume. Each automation can include an AI Voice Call Follow-Up that phones shoppers who did not respond, with its own delay, retry gap, maximum attempts and a custom opening message.

## Create and run an email automation
Open Email Automation, choose the campaign, press New Automation, pick the audience (all shops or one shop), the sequence steps and templates, batch size and iterations, and start it. It queues emails through the same outbox as Outreach. You can open an automation to see its shoppers, sent counts and stopped counts, and turn the voice call follow-up on or off.

## Bulk Voice Call
Bulk Voice Call lets you paste a list of phone numbers (up to 100) or pick saved numbers, add an optional opening message and press Start Bulk Call. The AI phones them one at a time with a real conversation, from the Plivo phone number configured for the account. The batch table shows each call's status and, if a call ended early, who ended it and why. Transcripts appear under Call Tracking. Calls cost money and are only placed after you confirm.

## Email Tracking and Call Tracking
Email Tracking shows sent, opened, clicked and accepted per campaign with each shopper's timeline. Call Tracking is separate and shows the outcome and transcript of each AI voice call, plus the recording when call recording is switched on. Click a row for the full timeline.

## Email Templates
Templates has built-in templates (Standard Invitation, Urgent Assignment, Bonus Opportunity, Reminder, Follow-Up and Custom Email) and your saved templates. You can create a template by hand or generate one with AI, use variables like shopper name and assignment link, preview it and reuse it in Outreach and automations.

## Social Media posts
Social Media has two tabs: Posts and Connected Accounts. New Post opens the composer where you pick the campaign and destinations, write the post text or use Generate with AI, Custom Prompt, Suggest Prompt from Shop Data, Attach Document and Attach Photo, press Generate Image for a graphic, then Save Draft, Schedule (date, time and timezone) or Publish Now. Posts can be region-targeted: each shop's state is matched to destinations that cover it so recruitment ads reach shoppers near the shops that need them.

## Connect social accounts
In Connected Accounts you link the brand's social destinations. Facebook uses a real Meta OAuth connection (when ISN has configured the Meta app), and Facebook Groups work through a manual posting workflow. Other destinations (Instagram, LinkedIn, Twitter/X, JobSlinger, TrustedHerd) are managed as connected accounts. Publishing to real accounts always needs your confirmation.

## Insights and Reports
Insights (a top-level page and a tab inside each campaign) lists findings for your campaigns such as shops with insufficient coverage, click-through rate and low response rate, and the campaign tab also has AI cards for campaign health, performance, a requirement parser (turns a plain-language requirement into structured criteria) and feedback analysis. Reports shows Campaign Progress, Completion Rate, Response Rate and Recruitment Coverage for your campaigns and lets you export campaign reports as PDF, XLSX or CSV.

## Profile and account
Profile (top-right menu, Profile & settings) has an Organization section with your company details, a Change Password form (current, new and confirm password) and a Danger Zone for deactivating or deleting the account, which needs your password. The assistant can read your profile but cannot change passwords or delete the account.

## Notifications
The bell icon lists alerts such as shops with low coverage and activity on your campaigns, each linking to the relevant page.

## Voice assistant
A microphone button turns on the "Hey Assistant" voice assistant: after one-time microphone permission, say "Hey" to start, keep talking turn after turn, and say "Hey, stop listening" to end. It can answer from your data and do tasks just like the chat assistant and always asks before sending, calling or changing anything.

## Admin portal pages
The Admin portal: Dashboard (global KPIs), Tracking (the full invitation funnel with per-shopper timelines and the ISN ATTRIBUTED badge), Insights (platform-wide findings), Users (client users and shoppers), Client Activity (what client accounts have been doing), Audit Logs (a record of significant actions with who did them), Integrations (SASSIE, email, AI, maps and SMS connections with status Connected, Demo, Disconnected, Configuration Required) and Settings (read-only configuration). Admins and clients have separate portals; a client user cannot open admin pages.
