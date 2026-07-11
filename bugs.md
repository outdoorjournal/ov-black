When I had the agent remove the flight, the UI didn't update.
UI didn't update when I changed travel party

We need to handle day/timezone changes better.


AP:
Right hand side of the journal is unhelpful
Need to fix the detail view of a card
What does the invoice screen look like?


X Need to add Address
X Favorite Airport

X Medical for Profile (allergies)

Change onboarding prompt
Add a hello prompt to the new client flow.

X USD vs EUR
X Error messages don't render after refresh.

X When Agent talks to advisor, needs to switch voice to be talking about the traveler.

X Better chat field | and up arrow.

18:51:21 DEBUG   httpcore.http11  receive_response_body.failed exception=CancelledError('Cancelled via cancel scope 1137ad490; reason: deadline exceeded')  method=POST path=/sessions/7d474fd9-efa3-4385-a803-e3a65aee6435/turn  [c27a1998]

X Notes not needed in collection.
-> z-index for itin header

Future:
 * Sync OSINT with Brevo
 * Jetlag
 * Do OSINT on zipcode

Stop button

Demo Flow:

3. We are assuming that there is an article that has a special CTA to start a trip to Greece on our platform, so we'll just need that.
4. The user is already a user (makes it easier to demo). That user will be Robin Thurston. OSINT has been filled out with flattering and not creepy information.
5. CTA link took user to special new landing page that had known params (inbound campaign would have been set up ahead of time, so this makes sense). We would make an itinerary for this user behind the scenes and leverage the structure of the current intake screen, but we _know_ that it's for Olympus AND it's made for you specifically. We can have special imagery and the AI can know things. This has to be cool. It needs to narrow down specifics like dates and travel party... maybe fill in something about the profile?
6. Intake ends and he lands on the dashboard of the new itinerary he made. It looks great. The hero images makes sense for Mt Olympus.
7. The Agent automatically starts telling the traveler that it's building out the skeleton of the trip. It builds out an itinerary based on a lot real OV inventory AND we flesh out lots of mock inventory the same way we did for Japan. Hotels, the idea that we can reserve an Uber Black, etc.
8. We can ask questions about it and ask the agent to make changes
9. Agent adds articles to the collection (a reading list) and talks in the chat, too. These articles are from his properties:
  * outsideonline.com
  * climbing.com
  * backpacker.com



1. Open the advisor view and see what we know about him.
2. See the trip.
3. Able to take that trip and make it "trunk" and issue an invoice. The invoice is a real invoice that can be paid. We can see the invoice in the advisor view and the traveler view.


