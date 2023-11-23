import { Link } from "@remix-run/react";


export function getMenuButton(menu: menuItem[])
{
    let result: JSX.Element[] = [];
    for (let i = 0; i < menu.length; i++) {
        result.push(<Link to={`/${menu[i].path}`} ></Link>)
    }
    return (<div>{result.join('\n')}</div>);
}