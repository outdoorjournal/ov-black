Invoice problem.

1. So an Advisor has decided that there are enough approved nodes to make an invoice. Flights need to get booked and maybe a cornerstone adventure.

2. The Avisor needs to be sure they're looking at the official version of the trip. We'll worry about merging and diffing later. Let's for now assume that the Advisor is looking at the official version of the trip.

3. The advisor goes to the Invoices (now called the Finances) tab where they see a tabular breakdown of every item in the itinerary that has a cost. Use micro cards as extra visual in one of the cells. Next to each one will be the amount invoiced and the amount paid and the amount remaining.

We take a deposit on the trip and that deposit amount will eventually vary based on some backend business logic, but for now, you can assume that it's 100% of all flights, 20% of all other inventory.

Now you can see for each item whether the deposit has been paid or not just by inferring from the amount paid.

4. Below that, they see cards for each invoice they've issued. Each card must:
    - remind one of the invoice itself in its look and feel
    - show the invoice number, date, and amount
    - show the status of the invoice (draft, issued, paid)
    - show currency and the exchange rates and the dates at which that exchange rate were pulled
    - when the invoice expires (exchange rate needs to re-adjust)
    - allow the advisor to click into the invoice to see more details
    - See line items for the invoice. If that line item lined up with an itinerary item, show a micro card for that itinerary item in the line item. In either case, it should show what was invoiced and what was paid for that line item. If the invoice is in draft, allow the advisor to edit the line item and change things.

5. Issuing an invoice. Two main ways:
5a. A quick action button to capture the deposit for the trip. This will create a draft invoice with all the line items for the deposit and allow the advisor to issue it. The advisor can edit the line items before issuing it. The amounts are known. You need to know what currency you're paying in, but we already built that out. You just need to show the currency and the exchange rate and what it means for the amount in the target currency.
5b. a quick action button to capture the final invoice for the trip. This will create a draft invoice with all the line items for the final invoice and allow the advisor to issue it. The advisor can edit the line items before issuing it. The amounts are known.
5c. Manual new invoice. The same editing experience as above, but there's just nothing there. As you're helping them build out each line item, you need to let them select what they're charging for and be helpful. For example, showing a nice list of all the itinerary items and showing them what's left to invoice for each one. If they want to add a line item that doesn't line up with an itinerary item, let them do that too. They'll need to add tax, fees, whatever.

6. Issuing the invoice. Once the advisor is happy with the invoice, they can issue it. This will send it to the traveler and allow them to pay it. The advisor should be able to see when the traveler has viewed it and when they've paid it.

7. Voiding the invoice. The advisor should be able to void the invoice if they need to and it hasn't been paid. This will cancel the invoice and allow them to issue a new one. I would expect all of the numbers of what's been paid on what to readjust automatically.
