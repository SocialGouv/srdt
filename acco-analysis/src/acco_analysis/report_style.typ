// Style "rapport": a sans page with structure you can scan: numbered section tabs, the
// five findings in a panel, quotes as cards, figures in the accent colour.
// Only the look lives here; the text is in report.typ.
#let navy = rgb("#1b2a41")
#let accent = rgb("#b4491f")
#let tint = rgb("#f7f1ea")
#let card = rgb("#fbf8f4")
#let muted = luma(115)
#let hairline = luma(215)
#let sans = ("Avenir Next", "Helvetica Neue", "Libertinus Serif")

#let figures(d) = d.pairs().map(((k, v)) => (k, text(weight: "bold", fill: accent)[#v])).to-dict()

// a lead-in paragraph stays on the page of the clause it introduces
#let lead(body) = block(sticky: true, body)

#let quote-block(x, source: none, ui: none) = block(
  width: 100%,
  above: 1em,
  below: 1.2em,
  breakable: false,
  fill: card,
  stroke: 0.5pt + hairline,
  radius: 4pt,
  inset: (x: 12pt, y: 10pt),
)[
  #set par(justify: false, leading: 0.7em)
  #set text(hyphenate: false)
  #text(size: 10pt)[«~#x.text~»]
  #v(0.7em)
  #box(
    fill: accent.lighten(85%),
    radius: 2pt,
    inset: (x: 5pt, y: 2.5pt),
    text(size: 7.5pt, weight: "semibold", fill: accent.darken(15%))[#x.company · #x.year],
  )
  #h(0.5em)
  #text(size: 8pt)[#link(x.url)[#source]]
  #if x.ui != none [#h(0.6em)#text(size: 8pt)[#link(x.ui)[#ui]]]
]

#let title-block(title, subtitle) = {
  block(width: 100%, fill: navy, radius: 6pt, inset: (x: 22pt, y: 22pt), below: 1.6em)[
    #set par(justify: false, leading: 0.4em)
    #text(size: 25pt, weight: "bold", fill: white)[#title]
    #v(0.7em)
    #text(size: 11pt, fill: white.darken(18%))[#subtitle]
  ]
}

#let report(body, title: "", footer: none, home: none) = {
  set document(title: title)
  set page(
    paper: "a4",
    margin: (x: 2.3cm, top: 2.2cm, bottom: 2.4cm),
    footer: context {
      set text(size: 8pt, fill: muted)
      line(length: 100%, stroke: 0.4pt + hairline)
      v(-0.2em)
      if home != none { link(home, text(fill: muted)[#footer]) } else { footer }
      h(1fr)
      counter(page).display("1 / 1", both: true)
    },
  )
  set text(font: sans, size: 10.5pt, lang: "fr", fill: navy, hyphenate: true)
  set par(justify: true, leading: 0.78em, spacing: 1.05em)
  set heading(numbering: "1.1")
  // the narrow no-break space of the figures is missing from some fonts: draw it
  show "\u{202f}": h(0.2em)
  show link: set text(fill: accent)

  show heading.where(level: 1): it => {
    let number = if it.numbering != none {
      numbering(it.numbering, ..counter(heading).at(it.location()))
    }
    v(2em, weak: true)
    block(sticky: true, below: 0.9em)[
      #grid(
        columns: (auto, 1fr),
        column-gutter: 0.7em,
        align: horizon,
        if number != none {
          box(
            fill: accent,
            radius: 3pt,
            inset: (x: 7pt, y: 5pt),
            text(size: 12pt, weight: "bold", fill: white)[#number],
          )
        },
        text(size: 16pt, weight: "bold", fill: navy)[#it.body],
      )
    ]
  }
  show heading.where(level: 2): it => {
    let number = if it.numbering != none {
      numbering(it.numbering, ..counter(heading).at(it.location()))
    }
    v(1.5em, weak: true)
    block(sticky: true, below: 0.7em)[
      #box(width: 5pt, height: 5pt, fill: accent, baseline: -0.1em)
      #h(0.45em)
      #text(size: 12pt, weight: "bold", fill: navy)[
        #if number != none [#text(fill: accent)[#number]#h(0.4em)]#it.body
      ]
    ]
  }

  set list(
    marker: box(width: 4pt, height: 4pt, fill: accent, baseline: 0pt),
    indent: 0.2em,
    body-indent: 0.8em,
    spacing: 0.9em,
  )
  // the five findings: a panel with numbered discs
  set enum(
    numbering: n => box(
      width: 1.5em,
      height: 1.5em,
      fill: accent,
      radius: 50%,
      align(center + horizon, text(size: 8.5pt, weight: "bold", fill: white)[#n]),
    ),
    indent: 0pt,
    body-indent: 0.9em,
    spacing: 1.1em,
  )
  show enum: it => block(
    width: 100%,
    fill: tint,
    radius: 6pt,
    inset: (x: 14pt, y: 12pt),
    above: 1.2em,
    below: 1.4em,
    it,
  )

  // tables (the notes that compare figures): a rule under the header, light row rules
  set table(
    stroke: (x, y) => if y == 0 { (bottom: 1pt + navy) } else { (bottom: 0.4pt + hairline) },
    inset: (x: 7pt, y: 6pt),
  )
  show table.cell.where(y: 0): set text(weight: "bold", size: 9pt)
  show table: set par(justify: false)
  show table: set text(hyphenate: false)
  show table: set block(above: 1.1em, below: 1.2em)

  show outline: it => block(
    width: 100%,
    fill: tint,
    radius: 6pt,
    inset: (x: 16pt, y: 12pt),
    below: 1.4em,
    it,
  )
  show outline.entry.where(level: 1): it => {
    v(0.4em, weak: true)
    text(weight: "semibold", it)
  }
  show outline.entry.where(level: 2): it => text(size: 9.5pt, fill: muted, it)

  body
}
