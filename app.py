import os
from flask import Flask, request, redirect, url_for, send_file
from werkzeug.utils import secure_filename
import pandas as pd

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_csv(file_path):
    # Read the uploaded CSV file
    df = pd.read_csv(file_path)

    # Extract only the first 4 columns
    df = df.iloc[:, :4]

    # Rename column "day" to "purchase_date" and change field to datetime
    df.rename(columns={'day': 'purchase_date'}, inplace=True)
    df['purchase_date'] = pd.to_datetime(df['purchase_date'])

    # Find the first purchase date for each customer
    first_purchase = df.groupby('customer_email')['purchase_date'].min().reset_index()
    first_purchase.columns = ['customer_email', 'first_purchase_date']

    # Merge the first purchase date back into the original DataFrame
    df = pd.merge(df, first_purchase, on='customer_email')

    # Calculate the cohort month
    df['cohort_month'] = df['first_purchase_date'].dt.to_period('M')

    # Calculate the purchase month
    df['purchase_month'] = df['purchase_date'].dt.to_period('M')

    # Ensure total_sales is float for calculations
    df['total_sales'] = df['total_sales'].astype(float)

    # Create a customer type column
    df['customer_type'] = df.apply(lambda x: 'New' if x['purchase_date'] == x['first_purchase_date'] else 'Returning', axis=1)

    # Calculate the total amount spent by each cohort in each month
    cohort_monthly_spend = df.groupby(['cohort_month', 'purchase_month'])['total_sales'].sum().reset_index()

    # Calculate cumulative total amount spent by each cohort over time
    cohort_monthly_spend['cumulative_total_spent'] = cohort_monthly_spend.groupby('cohort_month')['total_sales'].cumsum()

    # Calculate the number of unique customers in each cohort
    cohort_sizes = df.groupby('cohort_month')['customer_email'].nunique().reset_index()
    cohort_sizes.columns = ['cohort_month', 'cohort_size']

    # Merge the cohort sizes with the cumulative spend data
    cohort_monthly_spend = pd.merge(cohort_monthly_spend, cohort_sizes, on='cohort_month')

    # Calculate the average cumulative total spent by each cohort
    cohort_monthly_spend['avg_cumulative_total_spent'] = cohort_monthly_spend['cumulative_total_spent'] / cohort_monthly_spend['cohort_size']

    # Calculate months since initial purchase
    cohort_monthly_spend['months_since_initial_purchase'] = (cohort_monthly_spend['purchase_month'] - cohort_monthly_spend['cohort_month']).apply(lambda x: x.n)

    # Pivot the table to get a clearer view of the data (Average LTV)
    ltv = cohort_monthly_spend.pivot_table(index='cohort_month', columns='months_since_initial_purchase', values='avg_cumulative_total_spent', fill_value=0)

    # Save the average LTV pivot table to a CSV file
    avg_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'ltv.csv')
    ltv.to_csv(avg_csv_path)

    # Pivot the table to get a clearer view of the data (Total Monthly Revenue)
    revenue = cohort_monthly_spend.pivot_table(index='cohort_month', columns='months_since_initial_purchase', values='total_sales', fill_value=0)

    # Save the total monthly revenue pivot table to a CSV file
    total_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'revenue_monthly.csv')
    revenue.to_csv(total_csv_path)

    # Save cohort sizes to a CSV file
    cohort_sizes_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cohort_sizes.csv')
    cohort_sizes.to_csv(cohort_sizes_csv_path, index=False)

    # Filter out first purchases to identify repeat purchases
    repeat_purchases = df[df['customer_type'] == 'Returning']

    # Calculate the number of repeat purchasers by cohort and purchase month
    repeat_purchasers = repeat_purchases.groupby(['cohort_month', 'purchase_month'])['customer_email'].nunique().reset_index()
    repeat_purchasers.columns = ['cohort_month', 'purchase_month', 'repeat_purchasers']

    # Merge repeat purchasers with cohort sizes to calculate the repeat purchase rate
    repeat_purchasers = pd.merge(repeat_purchasers, cohort_sizes, on='cohort_month')

    # Calculate the repeat purchase rate
    repeat_purchasers['repeat_purchase_rate'] = repeat_purchasers['repeat_purchasers'] / repeat_purchasers['cohort_size']

    # Calculate months since initial purchase for repeat purchasers
    repeat_purchasers['months_since_initial_purchase'] = (repeat_purchasers['purchase_month'] - repeat_purchasers['cohort_month']).apply(lambda x: x.n)

    # Pivot the table to get a clearer view of the data (Repeat Purchase Rate)
    repeat_purchase_rate = repeat_purchasers.pivot_table(index='cohort_month', columns='months_since_initial_purchase', values='repeat_purchase_rate', fill_value=0)

    # Save the repeat purchase rate pivot table to a CSV file
    repeat_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'repeat_purchase_rate.csv')
    repeat_purchase_rate.to_csv(repeat_csv_path)

    return avg_csv_path, total_csv_path, repeat_csv_path, cohort_sizes_csv_path

@app.route('/')
def upload_form():
    return '''
    <!doctype html>
    <title>Cohort Analysis Upload</title>
    <h1>Shopify Cohort Analysis</h1>
    <p>Upload your Shopify data to analyze cohorts</p>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=Upload>
    </form>
    '''

@app.route('/', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        avg_csv_path, total_csv_path, repeat_csv_path, cohort_sizes_csv_path = process_csv(file_path)
        return f'''
        <!doctype html>
        <title>Cohort Analysis Download</title>
        <h1>Success!</h1>
        <p>Look how much time you saved. Download your CSVs below:</p>
        <a href="{url_for('download_file', filename=os.path.basename(avg_csv_path))}">Download Average LTV CSV</a><br>
        <a href="{url_for('download_file', filename=os.path.basename(total_csv_path))}">Download Total Monthly Revenue CSV</a><br>
        <a href="{url_for('download_file', filename=os.path.basename(repeat_csv_path))}">Download Repeat Purchase Rate CSV</a><br>
        <a href="{url_for('download_file', filename=os.path.basename(cohort_sizes_csv_path))}">Download Cohort Sizes CSV</a><br>
        <a href="/">Upload another file</a>
        '''
    return redirect(request.url)

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
