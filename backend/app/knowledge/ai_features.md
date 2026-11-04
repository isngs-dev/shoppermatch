<!-- audiences: staff -->
# AI features: how they work

## AI shopper recommendations and the match score
For each shop the AI scores every shopper out of 100 using seven weighted factors: semantic similarity between the campaign or shop requirement and the shopper's profile (30 points), distance from the shop (20, zero beyond about 60 km), category experience (15), availability (15), completion history (10), rating (5) and previous work for the same client (5). Only real profile fields are used and the full breakdown is always shown (View Match Breakdown on a candidate card). Scores of 90+ are Top matches, 80-89 Strong, 70-79 Potential and below 70 Low. Inactive, unavailable, outside-radius and requirement-failing shoppers are excluded, and the analysis summary tells you how many of each.

## Exactly the shoppers a shop needs
The AI recommends precisely as many shoppers as a shop still needs (required minus those already selected), ranked best first and skipping anyone already invited. Everyone else stays visible as optional More candidates, which can only be invited when over-selection is allowed for that shop.

## Shop staffing status: filled, ready, short
Every shop is in one of three states, shown the same way everywhere. Filled means all required shoppers are already selected. Ready means the AI found exactly the shoppers still needed. Short means there are fewer eligible shoppers than open slots. A short shop shows the gap and the ways to close it.

## Radius, bonus reach and long distances
The search radius decides who counts as nearby. Widening it is free. A bonus pays for the trip, so each dollar of bonus extends how far a shopper is expected to travel by 10 km, and recommendations re-run with that extra reach. The AI suggests a bonus of 25 to 75 percent of the shop's pay depending on how much of the shop is missing, rounded to 5, never above three times the pay, and only worth suggesting when it actually brings the missing shoppers into reach. If the nearest eligible shopper is far (over 150 km) the shop is flagged as a long trip and recruiting locally through Social Media is suggested alongside.

## AI Autopilot: what it is
AI Autopilot recruits for every open shop of a campaign on its own, inside limits you set. For each shop it finds the shoppers needed, closes any gap by widening the radius, adding or raising a bonus and re-matching, then creates the invitations. It can run on a schedule for every campaign, including campaigns added later (for example synced through the API). It is on the AI Recommendations tab under the AI Autopilot card.

## AI Autopilot modes
Off does nothing. Review first prepares the invitations (approved, not sent) so you check and send them from Outreach. Fully automatic also emails the shoppers, each email with an opening paragraph written by AI for that shopper from their own profile. The default is Off until you switch it on, per campaign or for all your campaigns (the checkbox "Use these settings for all my campaigns, including ones added later").

## AI Autopilot limits and Fill every shop
Limits: comfortable radius (default 150 km), maximum bonus as a multiple of the shop's pay (default 2), minimum match score (default 40), maximum invitations per run (default 100) and maximum shops per shopper within a campaign (default 3). Fill every shop (on by default) makes it keep going when those are not enough, in this order: widen the radius up to the limit, let nearby shoppers take more than one shop, add a bonus, stretch the radius further with a bonus that pays for the trip, then accept weaker matches. A shop nobody can fill yet is shown as Searching, not as an error, and Autopilot retries every cycle and fills it as soon as a shopper becomes available. With Fill every shop off it stops at the limits and reports Needs attention.

## AI Autopilot safety rules
Always on whatever you set: never invite more shoppers than a shop needs, never someone who already has or declined an invitation for that shop, never an opted-out shopper, never one shopper on two shops in a single run unless sharing is needed, never a bonus above its ceiling, and an awarded bonus is never changed. Across all campaigns a shopper never holds more than 5 invitations they have not answered (a setting called the open-invitation cap). Every run is written to the audit log and the last report is shown on the card.

## Preview or run AI Autopilot
On the AI Autopilot card, Preview plan shows exactly what it would do (shops, radius changes, bonuses, shoppers) without changing or sending anything. Run now carries it out in the current mode, and asks you to confirm first in Fully automatic mode. A scheduler also runs every 5 minutes and processes each campaign whose mode is on at most once every 30 minutes. The report lists per shop the result (Staffed, Searching, Partly filled, Needs attention), what the AI did and which shoppers.

## Auto Assign (AI Assignment Optimization)
Auto Assign is a one-time proposal for a whole campaign: for each shop, best-fit first, it assigns its top-scoring eligible shopper who has not already been proposed elsewhere in the same pass, respecting each shop's remaining slots. Nothing is saved until you press Approve All. It differs from AI Autopilot, which acts on a schedule with limits and can send emails.

## AI email personalisation
Generate with AI in Outreach fills the subject and body with a personalised sentence taken from the selected shopper's own recorded experience, previous clients and city, plus real campaign and shop data. It never invents facts and it never sends by itself. In Fully automatic Autopilot mode an OpenAI model writes the opening paragraph of each email from the same real facts.

## AI acceptance probability
For a shopper and shop the AI can estimate how likely they are to accept, from their own invitation history smoothed against the platform-wide acceptance rate. With fewer than three recorded responses it says "Insufficient historical data" instead of guessing.

## AI requirement parser, health and insights
The requirement parser turns a plain-language requirement ("food and beverage experience within 20 km") into structured criteria that the matching uses. Campaign health and performance cards, anomaly detection, data-quality checks, next-best-action suggestions and feedback analysis summarise the data and point out problems, always based on stored records.

## AI voice call follow-up
When enabled on an email automation, shoppers who did not respond get an automated AI phone call that asks whether they are still interested, with a real conversation and an optional custom opening message. Calls are placed through Plivo from the configured phone number, may be recorded (and say so), respect opt-outs and a daily call limit, and their outcomes and transcripts appear under Call Tracking.

## AI image and post generation
In Social Media the composer can write a post with AI from the campaign or shop facts, draft an image prompt from shop data, and generate a promotional image with OpenAI image models (it falls back automatically if the first model is not available to the account) or turn an attached photo into a graphic. Nothing is published without your action.

## The chat assistant and the voice assistant
The chat assistant is an agent with tools. For signed-in users it can read live data and perform any action the user could do in the app by calling the app's own API as that user, so it never has more access than the person it acts for. Every change is two-step: it states exactly what will happen and waits for a clear yes before anything is sent, called, published, changed or deleted. Reads run immediately. The voice assistant uses the same abilities by speech.
