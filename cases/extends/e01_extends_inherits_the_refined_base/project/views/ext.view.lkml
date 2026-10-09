include: "/views/orders.view.lkml"
view: orders_ext {
  extends: [orders]
  dimension: extra { sql: ${TABLE}.extra ;; }
}
