include: "/orders.view"
view: +orders {
  dimension_group: created {
    timeframes: [date, month]
    label: "Order Created"
  }
}
