<!-- audiences: staff -->
# Frequently asked how-tos

## How do I add campaigns, shops and shoppers (how they get into the platform)
They are not created by hand in the Client portal. Campaigns, their shops and the shopper roster come from the source mystery-shopping platform (SASSIE) through the SASSIE synchronisation that an ISN administrator runs from Integrations, or from the demo data the system is seeded with. Once synchronised they appear under Campaigns, Shops and Shoppers. Requirement text on a campaign can be turned into structured criteria by the AI requirement parser.

## How do I send emails to many shoppers at once
Use Outreach. Choose the campaign, set Send to "All shops · all required shoppers" (every shop and every shopper it needs, in one send) or "Choose individually" and tick the shops and shoppers, pick a template, and send. Several shoppers are sent in batches through the outbox with retries. For a repeating multi-step sequence use Email Automation instead, which emails every recommended shopper in a campaign in steps. To let the AI do both the choosing and the sending, switch on AI Autopilot in Fully automatic mode.

## How do I invite one specific shopper to one specific shop
Open Outreach, choose the campaign, tick only that shop, tick only that shopper (Choose individually), and send. Or, in AI Recommendations, pick the shop and tick the shopper on their candidate card and approve. If the shop already has all the shoppers it requires, the system refuses the extra invitation unless you allow over-selection for that shop.

## How do I see who accepted
Open the campaign's Tracking tab or Email Automation → Email Tracking: each row is an invitation with its status (Accepted or Declined) and a click opens the full timeline. The Overview tab and the Dashboard funnel show the accepted count, and the Shops tab shows invited against required per shop.

## How do I follow up with shoppers who did not respond
Open the invitation in Tracking and use Send Follow-Up (a follow-up is a new email for an invitation that was already sent). For a whole campaign, an Email Automation can send reminder steps, and its AI Voice Call Follow-Up can phone shoppers who stayed silent. AI Autopilot also replaces a shopper who declined by inviting someone else for the freed slot.

## How do I stop or pause an automation
Open the automation in Email Automation and use Pause (keep its progress and resume later), Resume, or Stop (end it). Shoppers can be added or removed from an automation individually.

## How do I export data
On a campaign's Overview tab use EXPORT PDF, EXPORT XLSX or EXPORT CSV. The Reports page also lets you export campaign reports. The assistant can fetch the same numbers in chat.

## How do I find out why a shop is not filled
Open the campaign's AI Recommendations tab and pick the shop. The card at the top says whether it is Fully staffed, AI recommendation ready or a Recruitment gap, shows how many shoppers are required, selected and still needed, explains how many candidates were outside the radius or unavailable, and offers the next step: expand the radius, add a bonus or recruit locally. On the Map tab a red marker is a shop with low coverage.

## How do I fill a hard-to-fill shop
First widen the search radius from the shop's recruitment gap card. If that is not enough, add a bonus: it pays for the trip and extends reach. If nobody suitable is near the shop, recruit shoppers there with a region-targeted post from Social Media. Or switch on AI Autopilot with Fill every shop so the AI does these steps itself inside your limits.

## How do I mark a shop completed and award its bonus
Only ISN administrators confirm that a shop visit really happened (for example from SASSIE data). Marking the shop completed advances the earliest accepted invitation to completed and, if the client pledged a bonus for that shop, awards it to that shopper and emails the client a reminder to pay them. ShopperMatch never processes the payment.

## How do I recruit shoppers through social media
Open Social Media → Posts → New Post, pick the campaign, write or AI-generate the post and image, choose the destinations that cover the shop's region, and save as draft, schedule or publish. Region-targeted posting sends the post only to destinations that cover a shop of that campaign. Real publishing needs a connected account and your confirmation.

## How do I change the wording of the invitation email
In Outreach edit the subject and the live body before sending, or pick another built-in or saved template. To reuse your wording, save it as a template (Save as template). Templates and the composer support variables such as shopper name, campaign name, shop name, location, compensation, deadline and the assignment link; the assignment link is what makes tracking work, so keep it in the email.

## How do I read an invitation timeline
Click any invitation row in Tracking. The timeline lists each event with a time: invitation created, email queued, sent, delivered, opened, link clicked, assignment page visited, accepted or declined, plus chatbot activity, interest recorded, follow-ups and opt-outs.

## What are good example requests to give the assistant
Examples that work: "Which shops still need shoppers?", "How is outreach performing for campaign X?", "Show me the AI Autopilot status of campaign X and preview what it would do", "Create an email template for a reminder", "Send the invitation emails for shop Y" (it asks for a yes first), "Turn on AI Autopilot in review mode for all my campaigns", "Draft a social post for this campaign", "Explain how the match score works". You never need to give it ids; it looks things up by name.

## What the assistant cannot do (its limits)
What it can't or won't do: it cannot change passwords, delete accounts, manage users, change integration secrets or settings, connect OAuth social accounts, respond for a shopper, or do anything the signed-in user is not allowed to do. It will not send emails, place calls, publish posts, change data or delete anything without a clear yes in your next message. It cannot see the contents of your screen, but it knows which page you are on and can look up data through the app's own API.
