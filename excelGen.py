import pandas as pd
from faker import Faker
import random

# Initialize Faker
fake = Faker('en_IN')  # Indian locale

# Number of records
NUM_RECORDS = 10

data = []

for _ in range(NUM_RECORDS):
    name = fake.name()
    
    # Generate Indian-style phone number
    phone = f"+91{random.randint(6000000000, 9999999999)}"
    
    street = fake.street_address()
    city = fake.city()
    
    data.append([name, phone, street, city])

# Create DataFrame
df = pd.DataFrame(data, columns=[
    "Name", "Phone", "Billing Street", "Billing City"
])

# Save to CSV
file_name = "salesforce_test_data.csv"
df.to_csv(file_name, index=False)

print(f"CSV file generated: {file_name}")