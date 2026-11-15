let activeLocks = 0;
let previousDocumentOverflow = "";
let previousBodyOverflow = "";
let previousBodyPaddingRight = "";

export function acquireDocumentScrollLock() {
  let released = false;

  if (activeLocks === 0) {
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    previousDocumentOverflow = document.documentElement.style.overflow;
    previousBodyOverflow = document.body.style.overflow;
    previousBodyPaddingRight = document.body.style.paddingRight;

    if (scrollbarWidth > 0) {
      const bodyPaddingRight = Number.parseFloat(window.getComputedStyle(document.body).paddingRight) || 0;
      document.body.style.paddingRight = `${bodyPaddingRight + scrollbarWidth}px`;
    }

    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
  }

  activeLocks += 1;

  return () => {
    if (released) return;
    released = true;
    activeLocks = Math.max(0, activeLocks - 1);

    if (activeLocks === 0) {
      document.documentElement.style.overflow = previousDocumentOverflow;
      document.body.style.overflow = previousBodyOverflow;
      document.body.style.paddingRight = previousBodyPaddingRight;
    }
  };
}
