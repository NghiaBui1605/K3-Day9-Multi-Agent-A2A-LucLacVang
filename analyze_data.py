import pandas as pd

orders = pd.read_csv('data/olist_orders_dataset.csv', low_memory=False)
payments = pd.read_csv('data/olist_order_payments_dataset.csv', low_memory=False)
items = pd.read_csv('data/olist_order_items_dataset.csv', low_memory=False)

print('=== Order Status Distribution ===')
print(orders['order_status'].value_counts())
print()

# Find late deliveries
orders['delivered_dt'] = pd.to_datetime(orders['order_delivered_customer_date'], errors='coerce')
orders['estimated_dt'] = pd.to_datetime(orders['order_estimated_delivery_date'], errors='coerce')
orders['carrier_dt'] = pd.to_datetime(orders['order_delivered_carrier_date'], errors='coerce')

late_orders = orders[orders['delivered_dt'] > orders['estimated_dt']]
print(f'Late deliveries (delivered > estimated): {len(late_orders)}')

# Join items to check shipping_limit_date for seller handoff
items['shipping_limit_dt'] = pd.to_datetime(items['shipping_limit_date'], errors='coerce')
orders_with_items = orders.merge(items[['order_id','seller_id','shipping_limit_dt']], on='order_id', how='left')

# Late seller handoff: carrier received AFTER shipping limit
late_handoff = orders_with_items[orders_with_items['carrier_dt'] > orders_with_items['shipping_limit_dt']]
print(f'Orders with late seller handoff: {len(late_handoff["order_id"].unique())}')

# Late delivery with late seller
late_with_seller = late_handoff[late_handoff['order_id'].isin(late_orders['order_id'])]
print(f'Late delivery + late seller handoff: {len(late_with_seller["order_id"].unique())}')

# Late delivery with on-time seller (logistics fault)
late_logistics = late_orders[~late_orders['order_id'].isin(late_with_seller['order_id'])]
print(f'Late delivery + on-time seller (logistics): {len(late_logistics)}')

# Canceled with payment
canceled_ids = orders[orders['order_status'] == 'canceled']['order_id'].tolist()
canceled_with_payment = payments[payments['order_id'].isin(canceled_ids)].groupby('order_id')['payment_value'].sum()
canceled_paid = canceled_with_payment[canceled_with_payment > 0]
print(f'Canceled orders WITH payment > 0: {len(canceled_paid)}')

# Unavailable with payment
unavail_ids = orders[orders['order_status'] == 'unavailable']['order_id'].tolist()
unavail_with_payment = payments[payments['order_id'].isin(unavail_ids)].groupby('order_id')['payment_value'].sum()
unavail_paid = unavail_with_payment[unavail_with_payment > 0]
print(f'Unavailable orders WITH payment > 0: {len(unavail_paid)}')

# Split payment orders (>=2 payment rows, reconciled)
split_counts = payments.groupby('order_id').size()
split_orders = split_counts[split_counts >= 2].index
print(f'Orders with split payment (>=2 rows): {len(split_orders)}')

print()
print('=== Sample IDs for diverse input generation ===')
print(f'canceled_paid samples: {list(canceled_paid.index[:5])}')
print(f'late_seller samples: {list(late_with_seller["order_id"].unique()[:5])}')
print(f'late_logistics samples: {list(late_logistics["order_id"].iloc[:5])}')
print(f'split_payment samples: {list(split_orders[:5])}')
