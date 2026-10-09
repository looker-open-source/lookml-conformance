view: base_a {
  sql_table_name: a.t ;;
  dimension: a_field { sql: ${TABLE}.a ;; }
}
view: base_b {
  sql_table_name: b.t ;;
  dimension: b_field { sql: ${TABLE}.b ;; }
}
