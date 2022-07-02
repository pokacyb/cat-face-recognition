This is a cat face recognition API. Users will create an account and access the API via a free trial. They are also able to create a membership and have full access to the API. Stripe has been integretated to handle payments. The app is built with Django on the backend handling the API, while the front end is built with React. For the image recognition we are using OpenCV. I am planning to deploy this on Heroku or Digital Ocean.

## To run the app follow the instruction below

```bash
virtualenv catface
source env/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

```bash
npm i
npm start
```
