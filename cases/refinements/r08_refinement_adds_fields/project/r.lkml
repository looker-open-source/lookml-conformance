include: "/orders.view"
view: +orders {
  dimension: status { sql: ${TABLE}.status ;; }
  dimension_group: created {
    type: time
    sql: ${TABLE}.created_at ;;
  }
}
