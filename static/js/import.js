(function(){
  function makeElement(template) {
    var outer = document.createElement('div');
    outer.innerHTML = template;
    return outer.children[0];
  }

  function updateProgress(progressLine, event) {
    var status = JSON.parse(event.data);
    if (status.status === 'started' && status.current_image) {
      var completion = (status.current_image / status.total_images);
      progressLine.animate(completion);
    } else if (status.status === 'failed') {
      // TODO: Replace progress bar with alert that has more information about the error
    } else if (status.status === 'finished') {
      var manifestUuid = status.result.split('/').slice(-2)[0];
      window.location.href = '/view/' + manifestUuid;
    } else if (status.status === 'queued') {
      // TODO: Display queue position and an animated indiactor that it's queued
    }
  }

  function addProgressMonitor(metsUrl, status) {
    var progressElement = makeElement('<div class="progress">');
    document.querySelector('.import-container').appendChild(progressElement);
    var progressLine = new ProgressBar.Line(progressElement, {
      'text': 'Queued'
    });
    var eventStream = new EventSource(status.sse_channel);
    eventStream.onmessage = updateProgress.bind(null, progressLine);
  }

  function addErrorState(status) {
    // TODO: Add error state and help text to form
  }

  function triggerImport(metsUrl, onLoad, onError) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/import', true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.addEventListener('load', function() {
      document.querySelector('.mets-input input').value = '';
      onLoad(JSON.parse(this.response));
    });
    xhr.addEventListener('error', function() {
      onError(JSON.parse(this.response));
    });
    xhr.send(JSON.stringify({url: metsUrl}));
  }

  document.querySelector('.mets-input button').addEventListener('click', function() {
    var metsInput = document.querySelector('.mets-input input');
    var button = document.querySelector('.mets-input button');
    var metsUrl = metsInput.value;
    if (metsUrl) {
      triggerImport(
        metsUrl,
        addProgressMonitor.bind(null, metsUrl),
        addErrorState);
      button.disabled = true;
      metsInput.disabled = true;
    } else {
      addErrorState({'message': 'Please enter a valid METS URL.'});
    }
    });
}());
