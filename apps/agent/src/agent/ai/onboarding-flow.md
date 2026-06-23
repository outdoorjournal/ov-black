When user accepts an invite, they need to land on a screen that that has the same black elegant look as the login page.

This will be their basecamp for all their interactions with the platform.

Because there are no itineraries yet, we want to get them talking and helping us to fill out the dossier in a unique and interactive way.

If there are no itineraries associated with that user, in the middle of screen where you would ordinarily show them all their itineraries, you instead show them an elegant prompt.. sort of like how Google just show the search bar. It would be the AI asking them one of a bank of possible open-ended questions that we would pre-define. One such is "What is one thing you always wanted to do, but never got the chance?"

The idea here is to have them answer. As soon as they do, that one prompt / text box morphs into a converation view (seamlessly) where the user can have a back and forth with the AI. The AI would ask follow up questions to get more details about that one thing they want to do, and then it would start filling out the dossier based on their answers.

As the user answers, I want you to adjust the ambience of the screen. There is existing code for this that I want you to understand and possibly re-use. The idea is that the screen should feel like it's responding to the user, and that the ambience is reflecting the vibe of what they're saying. So if they say "I want to go to Paris and eat croissants", maybe we have a little Eiffel Tower appear in the background, and the colors shift to be more French cafe-like. If they say "I want to go hiking in the mountains", maybe we have some mountains appear and the colors shift to be more earthy and natural.

At any time, they need to be able to leave the covnersation.

Now this is tricky because they still won't have an itinerary. We can't just keep bugging them with the "first time flow". That means we need to recognize that we've already conversed and turn that "single elegant prompt" UI into something else. We plan on having persistent AI chat on this Basecamp view, so maybe that chat view just invites them to continue the conversation at any time.

