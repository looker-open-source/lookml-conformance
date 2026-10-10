connection: "wh"
include: "/orders.view"
explore: customer_orders {
  view_name: orders
}
explore: +customer_orders {
  label: "Customer Orders"
}
