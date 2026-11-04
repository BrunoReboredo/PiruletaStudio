(function (root) {
  'use strict';
  class BoostTween {
    constructor(duration = 200) {
      this.duration = duration;
      this.states = new Map();
    }
    value(key, now) {
      const state = this.states.get(key);
      if (!state || state.to === null) return null;
      const elapsed = Math.max(0, Math.min(1, (now - state.start) / this.duration));
      return state.from + (state.to - state.from) * elapsed;
    }
    set(key, target, now) {
      target = target === null ? null : Math.max(0, Math.min(100, target));
      const previous = this.states.get(key);
      if (previous && previous.to === target) return;
      const current = this.value(key, now);
      this.states.set(key, {
        from: current === null || target === null ? target : current,
        to: target,
        start: now,
      });
    }
    retain(keys) {
      for (const key of this.states.keys()) {
        if (!keys.has(key)) this.states.delete(key);
      }
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { BoostTween };
  else root.BoostTween = BoostTween;
})(typeof globalThis !== 'undefined' ? globalThis : this);
