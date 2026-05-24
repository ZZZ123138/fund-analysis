"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";

interface Props {
  target: number;
  decimals?: number;
  suffix?: string;
  prefix?: string;
  duration?: number;
  className?: string;
}

export default function AnimatedCounter({
  target,
  decimals = 0,
  suffix = "",
  prefix = "",
  duration = 1.8,
  className = "",
}: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (!ref.current || hasAnimated.current) return;
    hasAnimated.current = true;

    const el = ref.current;
    const obj = { val: 0 };

    gsap.to(obj, {
      val: target,
      duration,
      ease: "power2.out",
      onUpdate() {
        const formatted =
          decimals > 0
            ? obj.val.toFixed(decimals)
            : Math.round(obj.val).toLocaleString();
        el.textContent = prefix + formatted + suffix;
      },
    });
  }, [target, decimals, suffix, prefix, duration]);

  return (
    <span ref={ref} className={className}>
      {prefix}0{suffix}
    </span>
  );
}
