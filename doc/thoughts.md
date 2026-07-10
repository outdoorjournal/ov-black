Invoice problem.

Waiting cards added in places

Simplified traveler interface

Process of moving things to "proposed"

Analysis really needs to be a sidebar

Notes and State

f2d6a296-08e7-4350-8cd5-484767ba3867/timeline


We need to talk about the "proposed" status. I'm not clear whether it's on the itinerary or whether it's on the nodes themselves, but ultimately, here's what I need:

1. An advisor needs to be able to make an itinerary completely until they decide the traveler can see it.
2. They then work together until the traveler "approves" items. That effectively locks it in and that's when the Advisor would issue invoices to move them to a "booked" state. This lets things happen incrementally.
3. Travelers can make their own itineraries without the Advisor at first.

What I think works is that we use the fork system. We have this "advisor official version" and "traveler version". Let's use this concept to our advantage.

It looks like we have a system where we need three forks. You have the "advisor working fork" the "official fork" that gets transacted on / booked and then you have the "traveler fork".

It works well. A traveler makes an itinerary without the advisor. 

An advisor can make an itinerary without the traveler. 

When the advisor is ready, they can "publish" their itinerary to the official fork. The traveler can then see it and make changes to it in their own fork.

The process is about merging the two forks together. The advisor can see the changes the traveler made and vice versa. When they are both happy, the advisor can "publish" the itinerary to the official fork and then issue invoices to move it to a "booked" state.




Now, I'm worried about the traveler side of the experience.

I need to create qa scenarios and then ensure that the functionality is working. Some may already be implemented.

1. I log in for the first time.
2. In my Home page, I'm inspired. i see the same type of beautiful imagery that was on the main sign-in page, except now, it's more subtle and fits into the paper background almost as if it were a watermark in a travel journel paper.
3. There's a welcome message from Artemis that is appropriate for the time of day and what might be going on with my account.
4. I see my itinerary tile that the Advisor has created for me. It uses the beautful imagery from the itinerary or a placeholder and enough relevant data for me to understand what it is (name, timeframe, etc).
5. I click on my Itinerary.
6. Here's where I need help. The current landing is... bland. You're landing me on a 
7. Talking to AI to help me build it out.

I need help re-imagining how the traveler experiences their itinerary. Sure.. we can keep the expansive "Timeline" view, but I'm wondering if there isn't some efficient space usage format that isn't so overwhelming. It can also land right on the itinerary's dashboard if done well. That would let them start seeing the beauty right away.

Instead of the painful "edit brief" nonsense, we can have the editing of these specifics built over the hero image. An elegant edit-in-place experience that brings up UIs when it needs to. You can use a thin bar underneath the hero if you have to, but it's wasted space.

I imagine a version of this that scrolls vertically like a long, beautiful timeline on the left. Especially on desktop, we can use the right hand side to provide rich content that is reacting to what is chosen on the left.

Each node of the graph can be one of our beautiful cards. The cards can be expanded to show more information, and the right hand side can provide additional details, options, and actions related to the selected card. Inside the node circle, we can use color and iconography to indicate the type of node. You already have a full card spec / prototype that has icons and colors for each one.

Mockup:

    |
    _   _________
   / \ |
   \_/ |
    |  |
    |  |_________
    |
    |

As the user scrolls down and different nodes are deemed "active" (e.g. a balance of what's in the center of the viewport, vs something explicitly selected), the appearance of the UI can subtly and gradually change. It might be background imagery that slowly fades in in that barely colored watermark/watercolor style on the paper behind. There might be relevant lottie animations that are triggered.

Our goal is to create a rich, immersive experience that makes the user feel like they are exploring their itinerary in a beautiful and engaging way.

There is a lot of room in this design to convey additional status. For example, when a node has a problem, we can circle its circle in red and add additional visual near the card (for accessibility) and a way to get helpful explanations of what's going on.

There's room on the left to call attention to the node in other ways, too. An arrow pointing to it, etc.

You need a way to delineate days and nights.

We also need to acknowledge that the itinerary is a graph, not a linear timeline. We can use subtle visual cues to show that the nodes are connected and that there are multiple paths through the itinerary.

We also need to acknowledge that itineraries may last 2 days to 2 months. We need to make sure that the UI can handle both short and long itineraries gracefully. That means ways to see what day you're on, and ways to jump to different days.

When editing, it's easy to insert because you can click on the line between two nodes and insert a new node. You can also click on a node and move it to a different place in the itinerary.

Long stretches of time in between events and sleep / wake events can be "virtual" nodes.

Long periods of time can be longer lines maybe with a virtual node indicating elision, but still not 1:1 pixels to minutes. You can help them with visual cues that there is more scrolling down to do.. shadows, a jump button.

You should think of the experience of scrolling through the itinerary as a journey in itself. Like watching a movie explaining what fun you'll have.

You can even imagine a full-screen mode that does just that. It's so beautiful and engaging that it can slowly autoscroll without the distractions of the chat or hero part.