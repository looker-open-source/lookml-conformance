view: orders {
  # LookML comment outside block
  sql_table_name: raw.orders ;;
  dimension: tag_hash {
    sql: CONCAT('#', ${TABLE}.tag) ;;
  }
}
