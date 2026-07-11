When I had the agent remove the flight, the UI didn't update.
UI didn't update when I changed travel party

We need to handle day/timezone changes better.



AP:
Right hand side of the journal is unhelpful
Need to fix the detail view of a card
What does the invoice screen look like?


Need to add Address
Favorite Airport
Do OSINT on zipcode

Medical for Profile (allergies)

Change onboarding prompt
Add a hello prompt to the new client flow.

USD vs EUR
Error messages don't render after refresh.

When Agent talks to advisor, needs to switch voice to be talking about the traveler.


Better chat field and up arrow.
18:51:21 DEBUG   httpcore.http11  receive_response_body.failed exception=CancelledError('Cancelled via cancel scope 1137ad490; reason: deadline exceeded')  method=POST path=/sessions/7d474fd9-efa3-4385-a803-e3a65aee6435/turn  [c27a1998]

Notes not needed in collection.
z-index for itin header

Future:
 * Sync OSINT with Brevo
 * Jetlag


Stop button

Demo Flow:

1. Start with looking at an article
2. Starts with an article on climbing Mt Olympus in Greece. Traveler wants to go to Greece.
3. Clicks on special CTA in article to start a trip to Greece.
4. Was already a user (makes it easier to demo). We know it was Robin Thurston. OSINT filled out.
5. Lands on special new landing page that had known params. We make an itinerary and use the intake screen, but we _know_ that it's for Olympus AND it's made for you specifically. We can have special imagery and the AI can know things.
6. When landing on the main page, it's learned about the dates and with whom he will travel.
7. The Agent starts telling the traveler that it's building out the skeleton of the trip. It builds out an itinerary based on a lot real OV inventory AND we flesh out lots of mock inventory the same way we did for Japan. Hotels, the idea that we can reserve an Uber Black, etc.
8. We can ask questions about it and ask the agent to make changes
9. Agent adds articles to the collection (a reading list) and talks in the chat, too. These articles are from his properties:
  * outsideonline.com
  * climbing.com
  * backpacker.com

  

1. Open the advisor view and see what we know about him.
2. See the trip.
3. Able to take that trip and make it "trunk" and issue an invoice. The invoice is a real invoice that can be paid. We can see the invoice in the advisor view and the traveler view.


