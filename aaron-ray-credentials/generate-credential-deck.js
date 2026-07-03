const pptxgen = require("pptxgenjs");

const COLORS = {
  navyDark: "051428",
  navy: "0B1E3A",
  cream: "F2EFE6",
  gold: "C9A96E",
  goldMuted: "A68A55",
  text: "0B1E3A",
  textSoft: "2A3A52",
  white: "FFFFFF",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Aaron Ray";
pres.title = "Executive Credential Synthesis — Aaron Ray";
pres.subject = "AI Emotional Benchmarking | Forensic Audiovisual Analysis | Artificial Senses Systems";

// Helper: thin gold rule (instrument precision line)
function addGoldRule(slide, y, opts = {}) {
  const x = opts.x ?? 0.55;
  const w = opts.w ?? 8.9;
  slide.addShape(pres.shapes.LINE, {
    x,
    y,
    w,
    h: 0,
    line: { color: COLORS.gold, width: opts.width ?? 1.25 },
  });
}

// Helper: left gold accent bar (subtle instrument tick)
function addLeftGoldAccent(slide) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 0,
    w: 0.06,
    h: 5.625,
    fill: { color: COLORS.gold },
    line: { color: COLORS.gold, width: 0 },
  });
}

function addFooter(slide, pageLabel) {
  slide.addText("AARON RAY  •  EXECUTIVE CREDENTIAL SYNTHESIS", {
    x: 0.55,
    y: 5.32,
    w: 7,
    h: 0.22,
    fontFace: "IBM Plex Mono",
    fontSize: 8,
    color: COLORS.goldMuted,
    charSpacing: 1.5,
  });
  slide.addText(pageLabel, {
    x: 8.2,
    y: 5.32,
    w: 1.3,
    h: 0.22,
    fontFace: "IBM Plex Mono",
    fontSize: 8,
    color: COLORS.goldMuted,
    align: "right",
  });
}

// ============================================
// SLIDE 1: TITLE — Instrument Cover
// ============================================
const slide1 = pres.addSlide();
slide1.background = { color: COLORS.navyDark };

// Top architectural label
slide1.addText("INSTRUMENT DESIGN TIER", {
  x: 0.55,
  y: 0.42,
  w: 9,
  h: 0.28,
  fontFace: "Bebas Neue",
  fontSize: 11,
  color: COLORS.gold,
  charSpacing: 4,
  align: "left",
});

slide1.addText("EXECUTIVE CREDENTIAL SYNTHESIS", {
  x: 0.55,
  y: 0.95,
  w: 9,
  h: 0.42,
  fontFace: "Bebas Neue",
  fontSize: 16,
  color: COLORS.cream,
  charSpacing: 2.5,
});

// Primary name — massive, authoritative
slide1.addText("AARON RAY", {
  x: 0.55,
  y: 1.65,
  w: 9,
  h: 1.05,
  fontFace: "Bebas Neue",
  fontSize: 58,
  color: COLORS.cream,
  bold: false,
  charSpacing: -0.5,
});

// Specialization statement
slide1.addText("AI Emotional Benchmarking  •  Forensic Audiovisual Analysis  •  Artificial Senses Systems", {
  x: 0.55,
  y: 2.82,
  w: 9,
  h: 0.38,
  fontFace: "IBM Plex Mono",
  fontSize: 12,
  color: COLORS.gold,
  charSpacing: 0.6,
});

// Prominent gold rule
addGoldRule(slide1, 3.38, { x: 0.55, w: 8.9, width: 1.5 });

// Package architecture line
slide1.addText("Target Package Architecture", {
  x: 0.55,
  y: 3.62,
  w: 9,
  h: 0.26,
  fontFace: "IBM Plex Mono",
  fontSize: 9,
  color: COLORS.goldMuted,
  charSpacing: 1.2,
});

slide1.addText("Navy  •  Cream  •  IBM Plex Mono  •  Bebas Neue Headers  •  Gold Rules", {
  x: 0.55,
  y: 3.88,
  w: 9,
  h: 0.32,
  fontFace: "IBM Plex Mono",
  fontSize: 13,
  color: COLORS.cream,
});

// Bottom qualifier
slide1.addText("Prepared for strategic positioning in advanced AI sensory & emotional intelligence benchmark design.", {
  x: 0.55,
  y: 4.85,
  w: 8.9,
  h: 0.35,
  fontFace: "IBM Plex Mono",
  fontSize: 10,
  color: "8BA1B8",
  italic: true,
});

// ============================================
// SLIDE 2: SECTION 1 — Entertainment Industry Credential Base
// ============================================
const slide2 = pres.addSlide();
slide2.background = { color: COLORS.cream };
addLeftGoldAccent(slide2);

slide2.addText("01", {
  x: 0.55,
  y: 0.35,
  w: 1.2,
  h: 0.55,
  fontFace: "Bebas Neue",
  fontSize: 32,
  color: COLORS.gold,
});

slide2.addText("ENTERTAINMENT INDUSTRY CREDENTIAL BASE", {
  x: 1.55,
  y: 0.42,
  w: 8,
  h: 0.48,
  fontFace: "Bebas Neue",
  fontSize: 18,
  color: COLORS.navy,
  charSpacing: 0.8,
});

addGoldRule(slide2, 0.98);

slide2.addText("Operational Scale Statement", {
  x: 0.55,
  y: 1.18,
  w: 9,
  h: 0.28,
  fontFace: "Bebas Neue",
  fontSize: 11,
  color: COLORS.goldMuted,
  charSpacing: 1.5,
});

slide2.addText("Over 35 years directing human emotional response at scale across a major portfolio of commercial media properties, managing packaging, production, and executive execution pipelines that generated substantial global audience engagement and commercial performance.", {
  x: 0.55,
  y: 1.48,
  w: 8.9,
  h: 0.95,
  fontFace: "IBM Plex Mono",
  fontSize: 13,
  color: COLORS.text,
  lineSpacing: 18,
});

slide2.addText("Core Creative Elements Analyzed", {
  x: 0.55,
  y: 2.55,
  w: 9,
  h: 0.28,
  fontFace: "Bebas Neue",
  fontSize: 11,
  color: COLORS.goldMuted,
  charSpacing: 1.5,
});

slide2.addText("Continuous analysis of audience behavioral engagement metrics, tracking the interplay of soundtrack structures, comedic timing, and dramatic narrative architectures to maximize viewer completion rates and retention.", {
  x: 0.55,
  y: 2.85,
  w: 8.9,
  h: 0.95,
  fontFace: "IBM Plex Mono",
  fontSize: 13,
  color: COLORS.text,
  lineSpacing: 18,
});

slide2.addText("This foundation in mass-scale emotional direction provides the empirical base layer for constructing valid, predictive emotional benchmarks in AI systems.", {
  x: 0.55,
  y: 4.0,
  w: 8.9,
  h: 0.65,
  fontFace: "IBM Plex Mono",
  fontSize: 12,
  color: COLORS.textSoft,
  italic: true,
  lineSpacing: 17,
});

addFooter(slide2, "02 / 06");

// ============================================
// SLIDE 3: SECTION 2 — Forensic Audiovisual Expertise
// ============================================
const slide3 = pres.addSlide();
slide3.background = { color: COLORS.cream };
addLeftGoldAccent(slide3);

slide3.addText("02", {
  x: 0.55,
  y: 0.35,
  w: 1.2,
  h: 0.55,
  fontFace: "Bebas Neue",
  fontSize: 32,
  color: COLORS.gold,
});

slide3.addText("FORENSIC AUDIOVISUAL EXPERTISE", {
  x: 1.55,
  y: 0.42,
  w: 8,
  h: 0.48,
  fontFace: "Bebas Neue",
  fontSize: 18,
  color: COLORS.navy,
  charSpacing: 0.8,
});

addGoldRule(slide3, 0.98);

const forensicItems = [
  {
    title: "Forensic Phonetics & Witness Qualifications",
    body: "Direct alignment with the foundational principles established in Hollien (1990), establishing core competencies in forensic acoustics, voice identification protocols, and the scientific authentication of audio evidence within legal chains of custody.",
  },
  {
    title: "Acoustic Signal Analysis & Trained Listener Frameworks",
    body: "System integration of Schiller & Koster (1998) methodologies, standardizing trained-listener verification loops to isolate micro-auditory variations, acoustic anomalies, and speech pattern anomalies.",
  },
  {
    title: "Psychological Stress Tracking & Voice Security",
    body: "Application of Acoustics of Crime parameters to track physiological stress signatures, frequency fluctuations, and sub-vocal indicators within voice streams. These parameters serve as the direct foundation for developing modern synthetic voice identification engines and deepfake detection software.",
  },
];

let yPos = 1.15;
forensicItems.forEach((item, idx) => {
  slide3.addText(item.title, {
    x: 0.55,
    y: yPos,
    w: 8.9,
    h: 0.26,
    fontFace: "Bebas Neue",
    fontSize: 11,
    color: COLORS.goldMuted,
    charSpacing: 1.2,
  });
  yPos += 0.26;
  slide3.addText(item.body, {
    x: 0.55,
    y: yPos,
    w: 8.9,
    h: idx === 2 ? 0.85 : 0.72,
    fontFace: "IBM Plex Mono",
    fontSize: 12.5,
    color: COLORS.text,
    lineSpacing: 17,
  });
  yPos += (idx === 2 ? 0.95 : 0.82);
  if (idx < 2) addGoldRule(slide3, yPos - 0.12, { width: 0.75 });
});

addFooter(slide3, "03 / 06");

// ============================================
// SLIDE 4: SECTION 3 — AI/ML Technical Credentials
// ============================================
const slide4 = pres.addSlide();
slide4.background = { color: COLORS.cream };
addLeftGoldAccent(slide4);

slide4.addText("03", {
  x: 0.55,
  y: 0.35,
  w: 1.2,
  h: 0.55,
  fontFace: "Bebas Neue",
  fontSize: 32,
  color: COLORS.gold,
});

slide4.addText("AI/ML TECHNICAL CREDENTIALS", {
  x: 1.55,
  y: 0.42,
  w: 8,
  h: 0.48,
  fontFace: "Bebas Neue",
  fontSize: 18,
  color: COLORS.navy,
  charSpacing: 0.8,
});

addGoldRule(slide4, 0.98);

const aiItems = [
  {
    title: "Frontier Architectural Frameworks",
    body: "Direct technical proficiency across machine learning models and frameworks, encompassing early implementations in TensorFlow and YOLOv3 object detection environments, alongside deep data tuning inside advanced natural language processing architectures.",
  },
  {
    title: "Generative Music & Audio Networks",
    body: "Technical execution tracking across advanced neural audio generation pipelines, including Google's Magenta platform, OpenAI Jukebox architectures, and digital acoustic sequence engines like EarSketch.",
  },
  {
    title: "Specialized Deep Learning Credentials",
    body: "Academic and practical training certifications in deep learning, sequence modeling, and natural language processing architectures from leading research institutions, including Johns Hopkins University and the University of Michigan.",
  },
];

yPos = 1.15;
aiItems.forEach((item, idx) => {
  slide4.addText(item.title, {
    x: 0.55,
    y: yPos,
    w: 8.9,
    h: 0.26,
    fontFace: "Bebas Neue",
    fontSize: 11,
    color: COLORS.goldMuted,
    charSpacing: 1.2,
  });
  yPos += 0.26;
  slide4.addText(item.body, {
    x: 0.55,
    y: yPos,
    w: 8.9,
    h: 0.78,
    fontFace: "IBM Plex Mono",
    fontSize: 12.5,
    color: COLORS.text,
    lineSpacing: 17,
  });
  yPos += 0.88;
  if (idx < 2) addGoldRule(slide4, yPos - 0.14, { width: 0.75 });
});

addFooter(slide4, "04 / 06");

// ============================================
// SLIDE 5: SECTION 4 — The Artificial Senses Framework
// ============================================
const slide5 = pres.addSlide();
slide5.background = { color: COLORS.cream };
addLeftGoldAccent(slide5);

slide5.addText("04", {
  x: 0.55,
  y: 0.28,
  w: 1.2,
  h: 0.48,
  fontFace: "Bebas Neue",
  fontSize: 28,
  color: COLORS.gold,
});

slide5.addText("THE ARTIFICIAL SENSES FRAMEWORK", {
  x: 1.55,
  y: 0.32,
  w: 8,
  h: 0.42,
  fontFace: "Bebas Neue",
  fontSize: 16,
  color: COLORS.navy,
  charSpacing: 0.6,
});

addGoldRule(slide5, 0.82);

// Core thesis callout box
slide5.addShape(pres.shapes.RECTANGLE, {
  x: 0.55,
  y: 0.98,
  w: 8.9,
  h: 0.72,
  fill: { color: "EDE8DC" },
  line: { color: COLORS.gold, width: 0.75 },
});

slide5.addText("Core Thesis", {
  x: 0.7,
  y: 1.03,
  w: 8.6,
  h: 0.22,
  fontFace: "Bebas Neue",
  fontSize: 9,
  color: COLORS.goldMuted,
  charSpacing: 1.5,
});

slide5.addText("Artificial Senses is the use of technology to augment, measure, and regulate human emotional and perceptual response—across therapeutic, legal, and entertainment domains.", {
  x: 0.7,
  y: 1.24,
  w: 8.6,
  h: 0.42,
  fontFace: "IBM Plex Mono",
  fontSize: 11.5,
  color: COLORS.navy,
  italic: true,
  lineSpacing: 15,
});

// Four pillars — 2x2 grid
const pillars = [
  { num: "I", title: "MUSIC AS MEDICINE", desc: "Engineering non-pharmacological behavioral regulation loops using targeted acoustic patterns and structured audio environments to manage attention and sensory processing, serving as a non-chemical intervention model for pediatric ADHD populations." },
  { num: "II", title: "JUDICIAL ANALYTICS", desc: "Processing and mapping public behavioral signals, structural micro-expressions, and linguistic patterns from legal decision-makers to decode cognitive biases and predict systemic litigation outcomes." },
  { num: "III", title: "FORENSIC AUTHENTICATION", desc: "Building robust, automated verification workflows that leverage multi-modal models to flag synthetic media generation, verify metadata, and preserve evidentiary integrity." },
  { num: "IV", title: "NARRATIVE PERSUASION", desc: "Calibrating the alignment of imagery, soundscapes, pacing, and dialogue setups against specific psychographic profiles to maximize narrative impact and retention." },
];

const colW = 4.25;
const rowH = 1.52;
const startY = 1.88;

pillars.forEach((p, i) => {
  const col = i % 2;
  const row = Math.floor(i / 2);
  const x = 0.55 + col * (colW + 0.2);
  const y = startY + row * (rowH + 0.08);

  // Pillar header with number
  slide5.addText(`PILLAR ${p.num}`, {
    x,
    y,
    w: colW,
    h: 0.20,
    fontFace: "IBM Plex Mono",
    fontSize: 8,
    color: COLORS.goldMuted,
    charSpacing: 1.8,
  });

  slide5.addText(p.title, {
    x,
    y: y + 0.20,
    w: colW,
    h: 0.26,
    fontFace: "Bebas Neue",
    fontSize: 11,
    color: COLORS.navy,
    charSpacing: 0.5,
  });

  addGoldRule(slide5, y + 0.48, { x, w: colW - 0.1, width: 0.6 });

  slide5.addText(p.desc, {
    x,
    y: y + 0.56,
    w: colW - 0.1,
    h: 0.92,
    fontFace: "IBM Plex Mono",
    fontSize: 10.5,
    color: COLORS.text,
    lineSpacing: 14,
  });
});

addFooter(slide5, "05 / 06");

// ============================================
// SLIDE 6: SECTION 5 — Benchmark Qualification Statement
// ============================================
const slide6 = pres.addSlide();
slide6.background = { color: COLORS.cream };
addLeftGoldAccent(slide6);

slide6.addText("05", {
  x: 0.55,
  y: 0.28,
  w: 1.2,
  h: 0.48,
  fontFace: "Bebas Neue",
  fontSize: 28,
  color: COLORS.gold,
});

slide6.addText("BENCHMARK QUALIFICATION STATEMENT", {
  x: 1.55,
  y: 0.32,
  w: 8,
  h: 0.42,
  fontFace: "Bebas Neue",
  fontSize: 16,
  color: COLORS.navy,
  charSpacing: 0.6,
});

addGoldRule(slide6, 0.82);

slide6.addText("Aaron Ray is uniquely qualified to design, validate, and publish advanced AI emotional and sensory benchmarks based on a rare convergence of cross-domain disciplines:", {
  x: 0.55,
  y: 0.98,
  w: 8.9,
  h: 0.52,
  fontFace: "IBM Plex Mono",
  fontSize: 12,
  color: COLORS.text,
  lineSpacing: 16,
});

const quals = [
  { num: "1", label: "Decades of Practical Mastery", text: "Extensive professional experience directing human emotional response at scale within commercial entertainment environments." },
  { num: "2", label: "Academic & Forensic Grounding", text: "Structural knowledge base spanning forensic phonetics, voice print identification, and real-world acoustic surveillance analysis." },
  { num: "3", label: "Hands-On Machine Learning Expertise", text: "Deep technical proficiency building, training, and fine-tuning neural networks, audio generation systems, and agentic CLI pipelines." },
  { num: "4", label: "Advanced Multi-Modal Integration", text: "Proven deployment of top-tier brain encoding foundation models (such as Meta's TRIBE v2 framework) to map digital media assets directly to biological neuro-imaging data." },
  { num: "5", label: "Published Benchmark Track Record", text: "Demonstrated capability in compiling rigorous, objective metrics, building on the methodology established in the previously published Kingsfield Legal Citation Benchmark to eliminate systemic evaluation bias." },
];

yPos = 1.55;
quals.forEach((q, idx) => {
  // Number in gold
  slide6.addText(q.num, {
    x: 0.55,
    y: yPos,
    w: 0.35,
    h: 0.32,
    fontFace: "Bebas Neue",
    fontSize: 14,
    color: COLORS.gold,
  });

  slide6.addText(q.label, {
    x: 0.95,
    y: yPos,
    w: 8.5,
    h: 0.24,
    fontFace: "Bebas Neue",
    fontSize: 10.5,
    color: COLORS.navy,
    charSpacing: 0.4,
  });

  slide6.addText(q.text, {
    x: 0.95,
    y: yPos + 0.24,
    w: 8.5,
    h: 0.38,
    fontFace: "IBM Plex Mono",
    fontSize: 10.5,
    color: COLORS.textSoft,
    lineSpacing: 14,
  });

  yPos += 0.66;
  if (idx < quals.length - 1) {
    addGoldRule(slide6, yPos - 0.06, { x: 0.95, w: 8.4, width: 0.5 });
  }
});

addFooter(slide6, "06 / 06");

// Write the file
pres.writeFile({ fileName: "/Users/aaronray/aaron-ray-credentials/Aaron-Ray-Executive-Credential-Synthesis.pptx" })
  .then(() => {
    console.log("✓ Generated: Aaron-Ray-Executive-Credential-Synthesis.pptx");
  })
  .catch(err => {
    console.error("Error generating presentation:", err);
    process.exit(1);
  });