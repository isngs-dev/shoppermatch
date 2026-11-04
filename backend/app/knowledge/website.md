<!-- audiences: visitor, shopper, staff -->
# The ShopperMatch.AI website and platform

## What is ShopperMatch.AI
ShopperMatch.AI is ISN's AI-powered shopper recruitment, outreach and attribution platform for mystery shopping. The home page tagline is "Fill every shop faster." It matches mystery shoppers to the shops that need a visit, emails them an invitation, and tracks exactly who opened the email, clicked it, visited the assignment page and accepted or declined. The flow shown on the home page is: SASSIE (the source shopping platform) → ShopperMatch.AI → AI Recommendation → ISN Outreach → Tracking → Shopper Response.

## Who uses the platform
Three kinds of people use it. ISN administrators run the whole system from the Admin portal. Client users (the brands that order mystery shopping, such as retail or restaurant chains) use the Client portal to manage their own campaigns. Mystery shoppers never log in: they get a personal secure link in an email and open the invitation page, where they can accept or decline and chat with the assistant.

## What the home page contains
The public home page has a top bar with a light/dark theme toggle and a Sign in button, a hero section ("Fill every shop faster" with a Sign in button and a View Shopper Invitation button that opens a sample invitation), a "How attribution flows" diagram (SASSIE → ShopperMatch.AI → AI Recommendation → ISN Outreach → Tracking → Shopper Response), three feature cards (unique UUID attribution, pixel plus click tracking, real-time outreach funnel), and a footer. The chat assistant is the round button at the bottom-left.

## Is this a demo or a live system
The website runs as a demonstration environment with synthetic (made-up) shoppers, shops and campaigns, as the footer says. Everything in it is functional: invitations, tracking links, accept and decline, dashboards and AI features all work on real database records. Real email delivery, voice calls and social publishing only happen when the matching provider (email provider, Plivo, Meta) has been configured by ISN.

## How to sign in
Press Sign in on the home page (or go to /login). Enter your email and password. ISN administrators land in the Admin portal (/admin/dashboard); client users land in the Client portal (/client/dashboard). In the demo, demo credentials are pre-filled on the sign-in screen. There is a "Forgot password?" link on the same screen.

## Create a client account
Businesses can register from the sign-in screen with "Create a client account" (the /signup page). You enter your company name, your contact name, your email and a password. The account is a Client user: it sees only its own company's campaigns and gets the Client portal.

## Forgot or reset my password
On the sign-in screen choose "Forgot password?", enter your email and a password reset link is sent. The link opens the reset-password page where you choose a new password. The assistant cannot reset passwords for you.

## How do I become a mystery shopper
Shoppers are not created through a public sign-up form on this website. ISN holds the shopper roster (sourced through SASSIE and ISN's own recruiting) and the platform picks the best-matching shoppers for each shop by location, experience, availability and track record. If you are matched you receive an email invitation with a personal link. To get matched more often, keep your profile details, availability and location up to date with ISN and complete the assignments you accept.

## What does it cost
Pricing is not published anywhere on this website and the assistant does not have price information, so it will not quote one. Shoppers are never charged: they are paid per completed assignment. A business that wants to use the platform can create a client account and explore the Client portal.

## What can the chat assistant do
The assistant is the chat button at the bottom-left of the website, the portals and the shopper invitation page. It answers questions about the platform and the website, how to do things step by step, and what each page and AI feature does. Signed-in ISN and client users can also ask it to look things up in live data and perform actions for them (it always asks for a clear yes before sending, calling, publishing, changing or deleting anything). Shoppers who open it from their invitation link get a campaign assistant that knows their campaign and shops. It replies in English, Hindi or Hinglish.

## Light and dark mode and phones
Every page has a theme toggle (sun or moon icon) for light and dark mode. The layout adapts to small screens, so the portals and invitation page work on a phone as well as a laptop.

## Where does my data go and is it private
Shopper data held by the platform is name, email, phone, city and location, categories of experience, availability, rating, completion rate and invitation history. Invitation links use random unguessable tokens, no raw IP addresses are stored, passwords are stored hashed, and tracking uses only a coarse browser summary. Client users only see aggregate shopper counts, never shopper names or contact details. Tracking is not anonymous: opens, clicks and responses are tied to your own invitation so ISN knows which invited shopper responded, but it uses no IP addresses or fingerprinting. There is no separate privacy-policy page on this website; the facts here are what the assistant can tell you. A shopper can stop messages at any time by telling the assistant, which records an opt-out that email, call and follow-up systems respect.

## Languages supported
The assistant replies in the language you write in: English, Hindi or Hinglish (Hindi in Roman script). The portals themselves are in English.

## What technology is it built with
ShopperMatch.AI is a single-page web app. The frontend uses React with TypeScript, Tailwind CSS, Recharts and Vite. The backend is Python with FastAPI (async), SQLAlchemy 2 and Pydantic, using PostgreSQL in production (SQLite for local runs). The AI features use OpenAI models (chat, text-to-speech and speech-to-text for the voice assistant, image generation) alongside the platform's own matching engine; email goes out through SendGrid, SMTP or EmailJS and AI phone calls through Plivo. The backend serves the web app and the API together from one address.

## How does tracking an invitation work
Every invitation has a random unguessable token. The email carries a 1×1 tracking image (opens), the button goes through a tracking link that records the click and then redirects to the shopper's own invitation page (visit), and Accept or Decline is recorded when the shopper presses it. Opens are approximate because some email apps block or prefetch images; clicks and responses are reliable.

## What if the assistant cannot answer
The assistant answers from the platform's own documentation and live data. If something is outside the platform (for example a question unrelated to ShopperMatch or mystery shopping) it says so. If you want a person at ISN to contact you it can take your details with your consent, but it is designed to answer without needing human support.
