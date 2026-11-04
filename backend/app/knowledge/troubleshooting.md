<!-- audiences: staff -->
# Troubleshooting and common questions

## My emails are not being delivered
Check these in order. 1) Which provider is active: with the mock provider delivery is only simulated, nothing leaves the system (Integrations shows the status). 2) Open Email Tracking or the invitation timeline: jobs show queued, sending, retrying, sent or failed with the last error. 3) A provider error such as "Maximum credits exceeded" (SendGrid) means the provider account has no sending credits left: top it up and queued jobs are retried. 4) Opted-out shoppers and shoppers without an email are skipped on purpose. 5) The outbox is throttled by a batch pause and a daily cap, so a big send finishes over time. A sent invitation cannot be sent twice.

## The tracking links point to localhost
The tracking, pixel and shopper-page links inside emails use the public base URL setting. If it says localhost, recipients outside your machine cannot open them. ISN needs to set PUBLIC_BASE_URL to the public address of the site.

## Opens look too high or too low
Opens are approximate because many email apps block or prefetch the tracking image, so they can be missed or counted early. Clicks and the shopper's response are the reliable signals.

## Bulk invitations say over-selection or too many shoppers
The shop already has its required number of shoppers selected. Either choose fewer shoppers, wait for a decline to free a slot, or allow over-selection for that shop (Allow over-selection) if you really want backups.

## AI Recommendations shows no shoppers or "Recommended 0"
Usually every eligible shopper is already invited for that shop, or nobody is within the radius. Look at the analysis line (candidates, eligible, outside radius). Widen the radius, add a bonus (which extends reach), or recruit locally through Social Media. If the shop is Fully staffed there is nothing left to recommend and More candidates holds the backups.

## A shop is short and widening the radius does nothing
If the nearest eligible shopper is hundreds or thousands of kilometres away the shop is flagged as a long trip. You can still expand to that distance, but the better fix is to recruit shoppers near the shop through Social Media, because the platform can only recommend shoppers that exist in its roster.

## Approve All did not show every approved shopper in Outreach
Choose Send to All shops · all required shoppers in Outreach so every shop with approved invitations is selected and every approved shopper is listed and ticked. Opening Outreach for a single shop shows only that shop's shoppers.

## AI Autopilot is not doing anything
Check the AI Autopilot card: if the mode is Off nothing runs. In Review first mode it prepares invitations but you send them from Outreach. Shops marked Searching have no eligible shopper right now and are retried automatically. Shoppers who already hold 5 unanswered invitations are skipped until they respond. Use Preview plan to see exactly what it would do, and Run now to run once immediately.

## AI Autopilot created too many invitations
Lower the limits (maximum invitations per run, maximum shops per shopper, comfortable radius), switch Fill every shop off, or set the mode to Off or Review first. Fill every shop deliberately goes past the radius limit and may add travel bonuses. Across all campaigns a shopper never holds more than 5 unanswered invitations.

## Image generation fails
Image generation needs the OpenAI key to be configured. If the first image model is not available to the account the system automatically tries the next model, so an error mentioning a missing model means none of the configured models are available to that key.

## A bulk voice call stopped after a sentence or two
Open the batch table: each call records who ended it and why. Common causes are the recipient's network blocking the caller ID, the recipient hanging up, or silence. The calls come from the Plivo number configured for the account.

## The chat assistant button is missing or says it is unavailable
The assistant needs the OpenAI key to be configured. When it is not, the launcher hides itself. If it is temporarily unavailable it retries and then reports that it could not reach the AI service.

## I cannot see a page or a button
The Admin and Client portals are different. A client user only sees their own campaigns and cannot open admin pages such as Users, Audit Logs or Integrations. Some buttons only appear in certain states, for example More candidates appears after a shop has all the shoppers it needs.

## Shopper names and contact details are hidden
Client users deliberately see only aggregate shopper counts for privacy. ISN administrators can open shopper profiles.

## How do I undo or cancel something the assistant did
Ask the assistant what it did. Invitations that were created but not sent can be left unsent; a sent email cannot be unsent. A bonus that has not been awarded can be edited or removed from AI Recommendations. The audit log records every significant action.

## Where can I see what the AI did
Admin Audit Logs record actions such as AI matching, approved recommendations, bulk invitations, bonus changes and AI Autopilot runs with who or what did them. The AI Autopilot card shows the last run report, and each invitation has its own event timeline.
