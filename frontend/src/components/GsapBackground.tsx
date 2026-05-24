"use client";

import { useEffect } from "react";
import gsap from "gsap";

export default function GsapBackground() {
  useEffect(() => {
    const el = document.getElementById("gsap-bg-gradient");
    if (!el) return;

    gsap.to(el, {
      opacity: 1,
      duration: 2,
      ease: "power1.inOut",
    });

    const tween = gsap.to(el, {
      backgroundPosition: "100% 100%",
      duration: 12,
      repeat: -1,
      yoyo: true,
      ease: "none",
    });

    return () => {
      tween.kill();
    };
  }, []);

  return (
    <div
      id="gsap-bg-gradient"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        opacity: 0,
        background:
          "radial-gradient(ellipse 80% 60% at 20% 40%, rgba(0,212,170,0.08), transparent 60%), radial-gradient(ellipse 60% 80% at 80% 60%, rgba(56,97,251,0.06), transparent 60%)",
      }}
    />
  );
}
