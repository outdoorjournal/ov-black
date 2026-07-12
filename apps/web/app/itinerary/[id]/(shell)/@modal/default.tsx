// Parallel-route default for the @modal slot. Renders nothing unless an
// intercept ((.)item/[nodeId]) fills it. Required so navigations that don't
// match the slot — and hard page loads — render it empty instead of 404-ing
// the whole segment.
export default function ModalSlotDefault() {
  return null;
}
