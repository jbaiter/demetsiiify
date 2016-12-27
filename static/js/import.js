// ChildNode.remove() polyfill for Internet Explorer
// from: https://github.com/jserz/js_piece/blob/master/DOM/ChildNode/remove()/remove().md
(function (arr) {
  arr.forEach(function (item) {
    item.remove = item.remove || function () {
      this.parentNode.removeChild(this);
    };
  });
})([Element.prototype, CharacterData.prototype, DocumentType.prototype]);

(function(){
  var statusTemplate = (
    '<div class="import-status">' +
    '  <div class="progressbar">' +
    '    <div class="progress"></div>' +
    '  </div>' +
    '  <div class="job-status"></div>' +
    '</div>');

  function makeElement(template) {
    var outer = document.createElement('div');
    outer.innerHTML = template;
    return outer.children[0];
  }

  function updateProgress(event) {
    var status = JSON.parse(event.data);
    if (status.status === 'started') {
      document.querySelector('.job-status').textContent = 'Processing';
      if (status.current_image !== undefined) {
        var completion = (status.current_image / status.total_images);
        document.querySelector('.progressbar .progress').style.width = (completion * 100) + "%";
      }
    } else if (status.status === 'failed') {
      // TODO: Replace progress bar with alert that has more information about the error
    } else if (status.status === 'finished') {
      var manifestUuid = status.result.split('/').slice(-2)[0];
      window.location.href = '/view/' + manifestUuid;
    } else if (status.status === 'queued') {
      document.querySelector('.job-status').textContent = 'Queued';
      var progressBar = document.querySelector('.progressbar .progress');
      if (!progressBar.dataset.queueLength) {
        progressBar.dataset.queueLength = status.position + 1;
      }
      var queueLength = progressBar.dataset.queueLength;
      var completion = (queueLength - status.position + 1) / queueLength;
      progressBar.style.width = (completion * 100) + "%";
    }
  }

  function addProgressMonitor(metsUrl, status) {
    var statusElement = makeElement(statusTemplate);
    statusElement.querySelector('.job-status').textContent = 'Queued';
    document.querySelector('.mets-input').remove();
    document.querySelector('.mets-importer').appendChild(statusElement);
    var eventStream = new EventSource(status.sse_channel);
    eventStream.onmessage = updateProgress;
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
