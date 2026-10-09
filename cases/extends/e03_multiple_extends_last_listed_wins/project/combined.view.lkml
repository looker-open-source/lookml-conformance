include: "/bases.view"
view: combined {
  extends: [base_a, base_b]
  dimension: own { sql: ${TABLE}.own ;; }
}
