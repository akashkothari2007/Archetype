/** SVG renderer for sheets/<id>.json. One <g> per semantic layer. */

const NS = "http://www.w3.org/2000/svg";

const LAYERS = [
  ["walls", "wall"],
  ["doors", "door"],
  ["windows", "window"],
  ["fixtures", "fixture"],
  ["grid", "grid"],
  ["room_tags", "room_tag"],
  ["dimensions", "dimension"],
  ["clear_spaces", "clear_space"],
];

function el(name, attrs = {}, children = []) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  for (const child of children) node.appendChild(child);
  return node;
}

function line(a, b, stroke) {
  return el("line", {
    x1: a[0], y1: a[1], x2: b[0], y2: b[1],
    stroke, "stroke-width": 2, fill: "none",
  });
}

export function layerCounts(geom) {
  return {
    wall: (geom.walls || []).length,
    door: (geom.doors || []).length,
    window: (geom.windows || []).length,
    fixture: (geom.fixtures || []).length,
    grid: (geom.grid?.x_axes?.length || 0) + (geom.grid?.y_axes?.length || 0),
    room_tag: (geom.room_tags || []).length,
    dimension: (geom.dimensions || []).length,
    clear_space: (geom.clear_spaces || []).length,
  };
}

export function renderSheet(svg, geom, hidden = new Set()) {
  const [w, h] = geom.size_pt;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.dataset.width = String(w);
  svg.dataset.height = String(h);

  const world = el("g", {
    id: "world",
    // Invert y so y-up sheet data renders correctly in SVG (y-down).
    transform: `matrix(1 0 0 -1 0 ${h})`,
  });

  const walls = el("g", { "data-layer": "wall" });
  for (const wall of geom.walls || []) {
    walls.appendChild(line(wall.a, wall.b, wall.cls === "loadbearing" ? "#5a2a2a" : "#222"));
  }

  const doors = el("g", { "data-layer": "door" });
  for (const door of geom.doors || []) {
    const [x0, y0, x1, y1] = door.bbox;
    doors.appendChild(el("rect", {
      x: x0, y: y0, width: x1 - x0, height: y1 - y0,
      fill: "none", stroke: "#b45a00", "stroke-width": 2,
    }));
  }

  const windows = el("g", { "data-layer": "window" });
  for (const win of geom.windows || []) {
    windows.appendChild(line(win.a, win.b, "#1a6aa3"));
  }

  const fixtures = el("g", { "data-layer": "fixture" });
  for (const fix of geom.fixtures || []) {
    const [x0, y0, x1, y1] = fix.bbox;
    fixtures.appendChild(el("rect", {
      x: x0, y: y0, width: x1 - x0, height: y1 - y0,
      fill: "#6a8f4e", "fill-opacity": 0.35, stroke: "#3d5a2c",
    }));
  }

  const grid = el("g", { "data-layer": "grid" });
  for (const axis of geom.grid?.x_axes || []) {
    grid.appendChild(line([axis.pos_pt, 0], [axis.pos_pt, h], "#9aa3b5"));
  }
  for (const axis of geom.grid?.y_axes || []) {
    grid.appendChild(line([0, axis.pos_pt], [w, axis.pos_pt], "#9aa3b5"));
  }

  const tags = el("g", { "data-layer": "room_tag" });
  for (const tag of geom.room_tags || []) {
    const t = el("text", {
      x: tag.xy[0], y: tag.xy[1], fill: "#1b1b18", "font-size": 14,
      transform: `translate(0 ${tag.xy[1] * 2}) scale(1 -1)`,
    });
    t.textContent = tag.text;
    tags.appendChild(t);
  }

  const dims = el("g", { "data-layer": "dimension" });
  for (const dim of geom.dimensions || []) {
    dims.appendChild(line(dim.a, dim.b, "#7a5a00"));
  }

  const clears = el("g", { "data-layer": "clear_space" });
  for (const cs of geom.clear_spaces || []) {
    const pts = (cs.polygon || []).map((p) => p.join(",")).join(" ");
    clears.appendChild(el("polygon", {
      points: pts, fill: "#3d7ea6", "fill-opacity": 0.15, stroke: "#3d7ea6",
    }));
  }

  for (const node of [walls, doors, windows, fixtures, grid, tags, dims, clears]) {
    const layer = node.getAttribute("data-layer");
    if (hidden.has(layer)) node.setAttribute("display", "none");
    world.appendChild(node);
  }
  svg.appendChild(world);
}

export function enablePanZoom(svg) {
  if (svg.dataset.panbound) return;
  svg.dataset.panbound = "1";
  let dragging = false;
  let last = [0, 0];

  svg.addEventListener("pointerdown", (e) => {
    dragging = true;
    last = [e.clientX, e.clientY];
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointerup", () => { dragging = false; });
  svg.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const vb = svg.viewBox.baseVal;
    const dx = e.clientX - last[0];
    const dy = e.clientY - last[1];
    last = [e.clientX, e.clientY];
    const scale = vb.width / svg.clientWidth;
    vb.x -= dx * scale;
    vb.y -= dy * scale;
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const vb = svg.viewBox.baseVal;
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    const rect = svg.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * vb.width + vb.x;
    const my = ((e.clientY - rect.top) / rect.height) * vb.height + vb.y;
    const nw = vb.width * factor;
    const nh = vb.height * factor;
    vb.x = mx - (mx - vb.x) * factor;
    vb.y = my - (my - vb.y) * factor;
    vb.width = nw;
    vb.height = nh;
  }, { passive: false });
}

export { LAYERS };
