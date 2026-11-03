// The look of the report as a web page (HTML export, embedded in the UI): semantic markup
// only, the colours and layout are the CSS of pages/report.html. Same names as
// report_style.typ, so report.typ builds both. The text is in report.typ.

// the figures are marked so the page can make them stand out
#let figures(d) = d.pairs().map(((k, v)) => (k, html.elem("span", attrs: (class: "n"), v))).to-dict()

#let lead(body) = body

#let quote-block(x, source: none, ui: none) = html.elem("figure", attrs: (class: "quote"))[
  #html.elem("blockquote")[«~#x.text~»]
  #html.elem("figcaption")[
    #html.elem("span", attrs: (class: "chip"))[#x.company · #x.year]
    #link(x.url)[#source]
    #if x.ui != none [#link(x.ui)[#ui]]
  ]
]

#let title-block(title, subtitle) = html.elem("header")[
  #html.elem("h1")[#title]
  #html.elem("p", attrs: (class: "sub"))[#subtitle]
]

#let report(body, title: "", footer: none, home: none) = {
  set document(title: title)
  set text(lang: "fr")
  set heading(numbering: "1.1")
  body
}
