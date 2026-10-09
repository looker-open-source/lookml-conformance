view: orders {
  derived_table: {
    sql: SELECT id FROM raw.orders WHERE note != ';' ;;
  }
  dimension: cleaned {
    sql: REGEXP_REPLACE(${TABLE}.note, ';', '') ;;
  }
}
