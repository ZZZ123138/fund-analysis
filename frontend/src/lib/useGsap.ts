"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/**
 * 数字滚动动画：从 0 递增到 target
 */
export function useCounter(target: number, opts?: { duration?: number; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!ref.current || target === 0) return;
    const el = ref.current;
    const decimals = opts?.decimals ?? 0;
    const suffix = opts?.suffix ?? "";

    const obj = { val: 0 };
    gsap.to(obj, {
      val: target,
      duration: opts?.duration ?? 1.8,
      ease: "power2.out",
      onUpdate() {
        el.textContent =
          (decimals > 0 ? obj.val.toFixed(decimals) : Math.round(obj.val).toLocaleString()) + suffix;
      },
    });
  }, [target, opts?.duration, opts?.decimals, opts?.suffix]);

  return ref;
}

/**
 * 卡片淡入上浮动画：多子元素依次出现
 */
export function useStaggerReveal(selector: string, deps: unknown[] = []) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const items = containerRef.current.querySelectorAll(selector);
    if (!items.length) return;

    gsap.fromTo(
      items,
      { opacity: 0, y: 40 },
      {
        opacity: 1,
        y: 0,
        duration: 0.5,
        stagger: 0.1,
        ease: "power3.out",
      }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}

/**
 * ScrollTrigger 驱动的淡入动画
 */
export function useScrollReveal() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;

    gsap.fromTo(
      el,
      { opacity: 0, y: 30 },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        ease: "power2.out",
        scrollTrigger: {
          trigger: el,
          start: "top 85%",
          once: true,
        },
      }
    );
  }, []);

  return ref;
}

export { gsap, ScrollTrigger };
