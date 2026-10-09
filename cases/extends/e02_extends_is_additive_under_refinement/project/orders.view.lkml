include: "/bases.view"
view: orders {
  extends: [base_a]
  dimension: id { sql: ${TABLE}.id ;; }
}
