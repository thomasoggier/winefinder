import { Link, useSearchParams } from '@remix-run/react';
import { FaLock, FaUserPlus } from 'react-icons/fa';

function AuthForm() {
  const [searchParams] = useSearchParams();
  const authMode = searchParams.get('mode') || 'login';

  const submitBtnCaption = authMode === 'login' ? 'Login' : 'Create User';
  const toggleBtnCaption =
    authMode === 'login' ? 'Create a new user' : 'Log in with existing user';

  return (
    <form method="post" className="form" id="auth-form">
      <div className="icon-img">
        {authMode === 'login' ?<FaLock/> : <FaUserPlus/>}
      </div>
      <p>
        <label htmlFor="name">Name</label>
        <input type="name" id="name" name="name" required />
      </p>
      <p>
        <label htmlFor="password">Password</label>
        <input type="password" id="password" name="password" minLength={2} />
      </p>
      <div className="form-actions">
        <button>{submitBtnCaption}</button>
        <Link to={authMode === 'login' ? '?mode=signup' : '?mode=login'}>
          {toggleBtnCaption}
        </Link>
      </div>
    </form>
  );
}

export default AuthForm;
