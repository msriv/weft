"use client";
// Same layout as the SVG graph, drawn with PixiJS once a story passes ~300 nodes.
import { Application, Graphics } from "pixi.js";
import { useEffect, useRef } from "react";
import type { Layout, Placed } from "@/lib/layout";

export default function StoryCanvas({ layout, onSelect }: { layout: Layout; onSelect: (n: Placed) => void }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const app = new Application();
    let dead = false;
    app.init({ width: layout.width, height: layout.height, background: 0x060708, antialias: true }).then(() => {
      if (dead || !host.current) return app.destroy();
      host.current.appendChild(app.canvas);
      app.canvas.style.width = "100%";
      const g = new Graphics();
      for (const e of layout.edges) g.moveTo(e.from.x, e.from.y).lineTo(e.to.x, e.to.y).stroke({ color: 0xff7a45, width: 1, alpha: 0.7 });
      for (const n of layout.nodes) {
        g.circle(n.x, n.y, n.r);
        if (n.kind === "document") g.fill(n.issuer?.is_party ? 0x9a9fa7 : 0xe8e6e1);
        else g.stroke({ color: 0xe8e6e1, width: 1 });
        if (n.anomalies.length) g.circle(n.x, n.y, n.r + 5).stroke({ color: 0xff7a45, width: 2 });
      }
      app.stage.addChild(g);
      app.stage.eventMode = "static";
      app.stage.on("pointertap", (ev) => {
        const p = ev.global;
        const hit = layout.nodes.find((n) => (n.x - p.x) ** 2 + (n.y - p.y) ** 2 <= (n.r + 4) ** 2);
        if (hit) onSelect(hit);
      });
    });
    return () => { dead = true; if (app.renderer) app.destroy(true); };
  }, [layout, onSelect]);
  return <div ref={host} aria-hidden="true" />;
}
