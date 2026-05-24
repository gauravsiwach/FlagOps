import React, {useEffect, useState} from 'react'

export default function App(){
  const [health, setHealth] = useState('unknown')

  useEffect(()=>{
    fetch('/api/health')
      .then(r=>r.json())
      .then(d=>setHealth(d.status))
      .catch(()=>setHealth('error'))
  },[])

  return (
    <div style={{fontFamily:'system-ui, Arial', padding:20}}>
      <h1>GrowthBook Feature Flag Ops (MVP)</h1>
      <p>Backend health: <strong>{health}</strong></p>
      <p>Use the backend `GET /api/diff` endpoint to fetch a sample diff.</p>
    </div>
  )
}
