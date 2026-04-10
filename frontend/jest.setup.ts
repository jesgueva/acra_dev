import "@testing-library/jest-dom";

// cmdk uses ResizeObserver and scrollIntoView which are not available in jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

Element.prototype.scrollIntoView = () => {};

// Radix Select uses pointer capture APIs not implemented in jsdom
Element.prototype.hasPointerCapture ??= function () {
  return false;
};
Element.prototype.setPointerCapture ??= function () {};
Element.prototype.releasePointerCapture ??= function () {};
