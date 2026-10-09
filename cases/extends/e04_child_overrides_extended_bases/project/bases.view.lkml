view: base_a {
  sql_table_name: a.t ;;
  dimension: id { sql: ${TABLE}.a_id ;; label: "A ID" }
  dimension: a_only { sql: ${TABLE}.a ;; }
}
view: base_b {
  sql_table_name: b.t ;;
  dimension: id { sql: ${TABLE}.b_id ;; }
}
