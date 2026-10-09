connection: "wh"
include: "/orders.view"
include: "/r_explore.lkml"
explore: customer_orders {
  view_name: orders
}
