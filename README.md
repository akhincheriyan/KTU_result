# KTU Result Analyser

A web-based AI-Powered tool designed to extract, analyze, and visualize student examination results from KTU (Kerala Technological University) result PDFs. Built with Flask, this application simplifies the process of generating detailed result statistics and reports.

## Features

*   **PDF Parsing**: Automatically extracts student results (Register Number, Department, Year, Component Grades) from official KTU result PDFs.
*   **Analytics Dashboard**:
    *   **Department-wise Breakdown**: View performance metrics separated by department (AI, CS, EC, ME, etc.).
    *   **Year-wise Analysis**: Filter results based on the admission year.
    *   **Subject-level Statistics**: Detailed pass/fail counts and percentages for each course.
*   **Excel Export**: Download comprehensive reports including:
    *   A summary analytics sheet.
    *   Individual sheets for each Department-Year batch.
*   **User Management**:
    *   Secure Signup and Login.
    *   Password Reset functionality.
    *   Personalized User History (save and access past analyses).
*   **History Tracking**: Keeps a record of uploaded files and generated reports for easy retrieval.

## Screenshots

*(Add screenshots of your application here after deployment)*

## Tech Stack

*   **Backend**: Python, Flask, SQLAlchemy (SQLite)
*   **Data Processing**: Pandas, OpenPyXL, PyMuPDF (fitz)
*   **Frontend**: HTML, CSS (Custom Design)

## Installation

1.  **Acquire the source code:**
    Extract the project zip file or clone the repository provided by the developer.
    ```bash
    cd KTU
    ```

2.  **Create a virtual environment (Recommended):**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up Environment Variables:**
    Create a `.env` file in the root directory and add the following:
    ```env
    FLASK_SECRET_KEY=your_secure_secret_key
    MAIL_USERNAME=your_email@gmail.com
    MAIL_PASSWORD=your_app_specific_password
    MAIL_DEFAULT_SENDER=your_email@gmail.com
    ```

5.  **Run the Application:**
    ```bash
    python app.py
    ```
    The app will start at `http://localhost:5000`.
    
## Account Creation

1.  Register for a new account or log in.
2.  Click on **New Analysis**.
3.  Upload a KTU Result PDF file.
4.  View the generated statistics on the dashboard.
5.  Download the detailed Python-generated Excel report.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
