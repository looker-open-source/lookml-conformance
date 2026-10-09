view: base_a {
  sql_table_name: a.t ;;
  dimension: shared { sql: ${TABLE}.from_a ;; }
  dimension: a_field { sql: ${TABLE}.a ;; }
}
view: base_b {
  sql_table_name: b.t ;;
  dimension: shared { sql: ${TABLE}.from_b ;; }
  dimension: b_field { sql: ${TABLE}.b ;; }
}
