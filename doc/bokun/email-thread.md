Jun 25, 2026, 3:27 AM (8 days ago)
	
	
to dhadden, me
Hey Daniel, 

Sam Jefferies gave me your email and said I should reach out to you - I'm the founder of OutdoorVoyage (as well as The Outdoor Journal, founded 2013), and we're looking to integrate the Bokun API into the next version of our platform. 

We're also a member of Tourpreneur and I've been in the industry for a while (won Booking's first early-stage startup award, was a Young Leader Driving Disruption at the ATTA World Summit, and a Red Bull Judge for many years). 

I saw your LinkedIn, I'd love to chat about your experiences as well!

Outdoor Voyage is a multi-day adventure travel platform, enabling customized multi-day adventure trips with local operators and seamless online booking and payments for US and international travelers. We have over 500 operators contractually signed up in 75 countries. 

Many of the our operators are asking us to integrate with Bokun so we can access their single day experience inventory easily, especially to complete bookings and reduce everyone's workload. As we develop our AI-driven system, this would be pretty important - would love to get your help on the API. 

I've copied my CTO, Chris Myers, who will be the tech lead. 

Thanks!

- AP

-- 
Apoorva Prasad (AP)
Founder/CEO, Outdoor Voyage Inc.
Listen to My Story on The Outdoor Journal Podcast

OutdoorVoyage
Apoorva Prasad
	
Jun 25, 2026, 9:46 AM (8 days ago)
	
	
to Partnerships, me
Hey Danny,

This is super helpful, thanks for laying it all out so clearly. That sounds right, we'll be a reseller then. 

Chris will dig into the API docs you sent over. The choice between Seller and OCTO sounds like the main thing we need to nail down, so let me discuss it with him.

How does the service fee work - is it per booking/transaction, and when is it due? 

Let me know if we need to get on call to run through the plan and commercials?

AP

On Thu, Jun 25, 2026 at 11:10 AM Partnerships Bokun <partnershipbokun-svc@tripadvisor.com> wrote:

    Hi AP,

    Great to hear from you, it's a pleasure to be connected. Happy to swap industry notes whenever suits.

    From your note, I understand OutdoorVoyage wants to connect to Bokun via our API so you can pull single-day experience inventory from operators (many of whom already sit on Bokun) and complete bookings directly inside your platform. That's exactly what our reseller setup is built for — and because a number of your operators are already on Bokun, connecting to them should be straightforward.

    Here's how it works in practice:

        You create a Bokun account and designate it as a reseller.
        You get access to our Marketplace, where you find and connect with suppliers — your existing operators plus thousands more across 75+ countries.
        You form a contract directly with each supplier, setting your own commercials. Bokun is purely the technology layer; the commercial relationship stays between you and the operator.
        Once a contract is live, that supplier's products are available in your Bokun account and, via the API, in your own platform. You'd act as merchant of record — collecting payment from the traveller and settling net rates with the operator — which aligns with how OutdoorVoyage already handles payments.

    On pricing: because you want API access, you'd be on our Expand plan — $149/month plus a service fee that scales with your average monthly Gross Booking Value (GBV):

        GBV under $200k = 1.5%
        GBV $200k–$500k = 1%
        GBV over $500k = 0.75%

    (For context, our entry plan is $49/month + 1.5%, but it's widget/manual only — no API — so Expand is the one that fits your build.) There's a 14-day free trial to get set up.

    For Chris — here are the API docs to assess the build. We maintain two APIs:

    1. Bokun (Seller) API — our proprietary REST API for fetching full product content (descriptions, photos, inclusions), availability, pricing, and creating/cancelling bookings:

        Building integration on the Bokun API
        Bokun (Seller) API swagger / technical spec

    2. OCTO Standard API — the open, industry-wide standard for availability, bookings and cancellations:

        Getting started with the Bokun OCTO API

    One quick steer given your AI-driven, content-rich platform: OCTO is currently transactional only — full content (photos/descriptions) is on its 2026 roadmap — so if pulling rich product content matters from day one, the Bokun Seller API is likely the better fit. Happy to talk through the trade-offs.

    Chris can build against our test environment straight away at extranet.bokuntest.com, and upgrade an account there using our test card details: 4111 1111 1111 1111 with any future expiry and CVV. If useful, I can also set you up with a test supplier account so you can run the full onboarding and booking flow end to end.

    To get started, you can login into your Bókun account here I have already added an additional 14 day free trial here. 

    Looking forward to hearing from you. 

    Regards, 

    Danny Hadden 
    The Bókun Partnerships Team 
    bokun.io


    On Thu, Jun 25, 2026 at 8:54 AM Daniel Hadden <dhadden@tripadvisor.com> wrote:


        Daniel Hadden

        Senior Global Partnerships Manager

        bokun.io 




Partnerships Bokun <partnershipbokun-svc@tripadvisor.com>
	
Jun 25, 2026, 9:57 AM (8 days ago)
	
	
to Apoorva, me
HI AP and Chris, 

Thank you for your reply. 

The booking fees are charged the month after the booking is taken so all bookings taken in May will be charged in June. The subscription fee is always charged for the coming month. 

I will be out of the office next week but Emmanuel in my team will be able to join a call please find his calendar here. 

We remain at your disposal.  

best regards, 

Danny Hadden 
The Bókun Partnerships Team 
bokun.io
1Password menu is available. Press down arrow to select.
