<!-- audiences: staff, visitor, shopper -->
# Key concepts and terms

## Campaign
A campaign is a mystery shopping project for one client, such as a store audit or a launch recruitment. It has a name, client, status, deadline and a set of shops. Campaigns are grouped as Active, Upcoming or Completed.

## Shop
A shop is one physical location that needs to be visited within a visit window. It has an address and coordinates, a number of required shoppers, a compensation amount, a category and a status such as open or completed.

## Shopper
A shopper is a mystery shopper with a profile: name, contact details, city and location, categories of experience, availability, rating, completion rate and number of previous assignments.

## Invitation
An invitation is one email offering one shopper one shop. It has a human reference such as INV-0001, a unique tracking token, a status and a timeline of events. Status moves forward only: created, sent, delivered, opened, clicked, accepted or declined.

## Tracking token and attribution
Every invitation has a random unguessable UUID token. The email's tracking pixel, the click link and the shopper's invitation page all carry it, so each open, click, visit and response is tied to exactly one invitation, its campaign, shop and shopper. The Tracking pages show this as ISN ATTRIBUTED.

## The outreach funnel
Sent, Delivered, Opened, Clicked, Accepted. Opened means the email's tracking image loaded, which is approximate because some email apps block or prefetch images. Clicked means the link was followed and is the more reliable signal. Visited means the assignment page loaded. Accepted and Declined are the shopper's own response.

## Coverage
Coverage tells how well a shop is staffed. Healthy means the required number of shoppers is invited, Medium means at least half, Low means less than half. It is shown as green, amber and red on the campaign map.

## Required shoppers and open slots
Each shop needs a number of shoppers. Selected counts invitations still in play (a decline frees the slot). Open slots are required minus selected, and the AI recommends exactly that many.

## Over-selection
Over-selection means inviting more shoppers than a shop requires, as backups. It is off by default and can be allowed per shop. When it is off the system refuses to go over the required number.

## Bonus
A bonus is an optional extra amount a client pledges for one shop to attract shoppers, on top of the shop's compensation. The client pays it directly; ShopperMatch only records it and reminds the client when the shop is completed.

## Search radius
The radius is how far from a shop the AI looks for shoppers. It can be widened. A bonus extends reach further. Shoppers outside it are listed as outside the radius in the analysis.

## Match score and classification
A match score is the 0 to 100 fit of a shopper to a shop. 90 and above is a Top match, 80 to 89 Strong, 70 to 79 Potential and under 70 Low match. The score breakdown shows points per factor.

## Outbox and throttling
Emails do not go out instantly: they are queued in a durable outbox and delivered by a background worker with retries. A global governor limits sending: a pause after a batch (default 1000 emails, 5 minutes) and a daily cap (default 5000). Opted-out shoppers are never emailed.

## Email provider
The platform sends through a provider chosen by configuration: mock (simulates delivery, the default), SendGrid, SMTP (for example Gmail) or EmailJS. With mock, nothing leaves the system. The Integrations page shows the connection status.

## Client versus admin
Admin users are ISN staff with full access to everything and the Admin portal. Client users belong to one brand and see only that brand's campaigns, with shopper data limited to counts. Both can use the chat assistant, which can only do what the signed-in user is allowed to do.

## SASSIE
SASSIE is the source mystery-shopping platform that ShopperMatch.AI can synchronise campaigns, shops and shoppers from. In demo mode integrations run on a demo adapter that is always labelled DEMO, never CONNECTED.
