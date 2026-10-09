view: orders {
  sql_table_name: raw.orders ;;
  dimension_group: created {
    type: time
    timeframes: [raw, date, week, month, year]
    sql: ${TABLE}.created_at ;;
  }
}
