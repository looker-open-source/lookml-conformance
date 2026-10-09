view: users {
  sql_table_name: raw.users ;;
  dimension: id { sql: ${TABLE}.id ;; }
  dimension: country { sql: ${TABLE}.country ;; }
}
